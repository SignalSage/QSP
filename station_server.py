#!/usr/bin/env python3
"""Local APRS messenger bridge. Python 3.9+, standard library only."""
import argparse, ipaddress, json, re, secrets, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
CALL = re.compile(r'^[A-Z0-9]{1,6}(?:-(?:[0-9]|1[0-5]))?$')

def callsign(value):
    value = str(value).strip().upper()
    if not CALL.fullmatch(value):
        raise ValueError('Use a callsign with an optional SSID from 0 to 15.')
    return value[:-2] if value.endswith('-0') else value

class State:
    def __init__(self, history=None):
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.code = secrets.token_hex(3).upper()
        self.sessions = set()
        self.history_path = history
        self.events = []
        self.commands = []
        self.enabled = False
        self.last_poll = 0
        self.call = ''
        self.owner = None
        self.failures = {}
        if history and history.exists():
            try:
                self.events = json.loads(history.read_text())[-1000:]
                for event in self.events:
                    if event.get('status') in ('pending', 'processing', 'transmitting'):
                        event['status'] = 'interrupted'
            except (ValueError, OSError, TypeError):
                self.events = []

    def save(self):
        self.events = self.events[-1000:]
        if self.history_path:
            temp = self.history_path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.events, ensure_ascii=True), encoding='utf-8')
            temp.replace(self.history_path)

    def online(self):
        return self.enabled and time.time() - self.last_poll < 12

    def update(self, ident, **values):
        for event in self.events:
            if event['id'] == ident:
                if event.get('status') in ('acknowledged', 'rejected') and values.get('status') in ('transmitting', 'sent', 'failed'):
                    return event
                event.update(values)
                self.save()
                return event
        return None

    def expire(self):
        now = time.time()
        if self.enabled and now - self.last_poll >= 12:
            self.disable()
        self.commands = [cmd for cmd in self.commands if now - cmd['time'] < 120]
        changed = False
        for event in self.events:
            if event.get('status') == 'pending' and now - event['time'] >= 120:
                event['status'] = 'expired'
                changed = True
            elif event.get('status') == 'transmitting' and now - event.get('claimed', event['time']) >= 180:
                event['status'] = 'interrupted'
                changed = True
            elif event.get('status') == 'processing' and now - event.get('claimed', event['time']) >= 15:
                event['status'] = 'interrupted'
                changed = True
        if changed:
            self.save()

    def disable(self):
        self.enabled = False
        self.commands.clear()
        for event in self.events:
            if event.get('status') == 'pending':
                event['status'] = 'cancelled'
        self.save()

class Handler(BaseHTTPRequestHandler):
    server_version = 'PacketLAN/0.13'
    def log_message(self, *_):
        pass

    def reply(self, value, status=200, mime='application/json'):
        body = json.dumps(value).encode() if mime == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(body)

    def local(self):
        return ipaddress.ip_address(self.client_address[0]).is_loopback

    def trusted_host(self):
        host = self.headers.get('Host', '').split(':')[0].lower()
        if host == 'localhost':
            return True
        try:
            address = ipaddress.ip_address(host)
            return address.is_private or address.is_loopback
        except ValueError:
            return False

    def station_auth(self):
        return self.local() and secrets.compare_digest(self.headers.get('X-Station-Token', ''), self.server.state.token)

    def phone_auth(self):
        return self.headers.get('X-Messenger-Token', '') in self.server.state.sessions

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 32768:
            raise ValueError('Invalid request size.')
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('JSON requests required.')
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            raise PermissionError('Cross-origin commands are blocked.')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError('Expected an object.')
        return data

    def do_GET(self):
        if not self.trusted_host():
            self.reply({'error': 'Use localhost or the computer LAN IP.'}, 403)
            return
        path = urlsplit(self.path).path
        state = self.server.state
        if path == '/api/bootstrap':
            if not self.local():
                self.reply({'error': 'Station controls are available on the station computer only.'}, 403)
                return
            self.reply({'token': state.token, 'code': state.code, 'urls': self.server.phone_urls})
        elif path == '/api/messages':
            if not self.phone_auth():
                self.reply({'error': 'Pair this device first.'}, 401)
                return
            with state.lock:
                state.expire()
                self.reply({'online': state.online(), 'call': state.call, 'events': state.events})
        elif path in ('/', '/messenger', '/station'):
            filename = 'custom_packet_browser_v0.13.html' if path == '/station' else 'messenger.html'
            if path == '/station' and not self.local():
                self.reply({'error': 'Open the station page using localhost on its computer.'}, 403)
                return
            try:
                self.reply((ROOT / filename).read_bytes(), mime='text/html;charset=utf-8')
            except OSError:
                self.reply({'error': 'Missing '+filename+'; extract all ZIP files into the same folder.'}, 404)
        else:
            self.reply({'error': 'Not found.'}, 404)

    def do_POST(self):
        if not self.trusted_host():
            self.reply({'error': 'Use localhost or the computer LAN IP.'}, 403)
            return
        state = self.server.state
        try:
            data = self.body()
            path = urlsplit(self.path).path
            with state.lock:
                state.expire()
                if path == '/api/pair':
                    ip = self.client_address[0]
                    failed = [t for t in state.failures.get(ip, []) if time.time()-t < 60]
                    if len(failed) >= 10:
                        self.reply({'error': 'Wait one minute before trying another code.'}, 429)
                        return
                    if not secrets.compare_digest(str(data.get('code', '')).upper(), state.code):
                        state.failures[ip] = failed + [time.time()]
                        raise PermissionError('Incorrect pairing code.')
                    if len(state.sessions) >= 100:
                        raise ValueError('Device limit reached; restart the server.')
                    token = secrets.token_urlsafe(32)
                    state.sessions.add(token)
                    self.reply({'token': token})
                elif path == '/api/send':
                    if not self.phone_auth():
                        raise PermissionError('Pair this device first.')
                    if not state.online():
                        self.reply({'error': 'Station sharing is off or the station page is disconnected.'}, 409)
                        return
                    to = callsign(data.get('to', ''))
                    text = str(data.get('text', ''))
                    if not 1 <= len(text) <= 67 or any(not 32 <= ord(c) <= 126 or c in '|~{' for c in text):
                        raise ValueError('Use 1–67 printable ASCII characters, excluding |, ~ and {.')
                    if text.startswith(('ack', 'rej')):
                        raise ValueError('Message text cannot start with ack or rej (reserved by APRS).')
                    request = str(data.get('request', ''))
                    if not re.fullmatch(r'[A-Za-z0-9-]{8,80}', request):
                        raise ValueError('Missing request identifier.')
                    old = next((e for e in state.events if e.get('request') == request), None)
                    if old:
                        self.reply(old)
                        return
                    if len(state.commands) >= 20:
                        self.reply({'error': 'Station is busy. Try again shortly.'}, 429)
                        return
                    ident = secrets.token_hex(8)
                    number = secrets.token_hex(2).upper()
                    event = {'id': ident, 'request': request, 'time': time.time(), 'direction': 'out', 'source': state.call, 'to': to, 'text': text, 'number': number, 'status': 'pending'}
                    state.events.append(event)
                    state.commands.append(dict(event))
                    state.save()
                    self.reply(event, 201)
                elif path.startswith('/api/station/'):
                    if not self.station_auth():
                        raise PermissionError('Station authorization required.')
                    if path == '/api/station/poll':
                        owner = str(data.get('owner', ''))
                        if not owner or len(owner) > 80:
                            raise ValueError('Missing station tab ID.')
                        if state.online() and state.owner != owner:
                            self.reply({'error': 'Another station tab already owns this bridge.'}, 409)
                            return
                        state.owner = owner
                        state.call = callsign(data.get('call', ''))
                        state.last_poll = time.time()
                        state.enabled = bool(data.get('enabled'))
                        if not state.enabled:
                            state.disable()
                        command = state.commands.pop(0) if state.enabled and data.get('ready') and state.commands else None
                        if command:
                            state.update(command['id'], status='processing', claimed=time.time())
                        self.reply({'command': command})
                    elif path == '/api/station/disable':
                        if state.owner == data.get('owner'):
                            state.disable()
                        self.reply({'ok': True})
                    elif path == '/api/station/event':
                        if state.owner != data.get('owner'):
                            raise PermissionError('Station tab does not own this bridge.')
                        if data.get('kind') == 'status':
                            status = data.get('status')
                            if status not in ('transmitting', 'sent', 'failed', 'interrupted'):
                                raise ValueError('Invalid transmission status.')
                            event = state.update(str(data.get('id')), status=status, detail=str(data.get('detail', ''))[:200])
                            if not event:
                                raise ValueError('Unknown message.')
                        elif data.get('kind') == 'received':
                            source, to = callsign(data.get('source', '')), callsign(data.get('to', ''))
                            if to != state.call:
                                raise ValueError('Not addressed to this station.')
                            text, number = str(data.get('text', ''))[:100], str(data.get('number', ''))[:5]
                            if data.get('ack') in ('ack', 'rej'):
                                for event in reversed(state.events):
                                    if event.get('direction') == 'out' and event.get('to') == source and event.get('source') == to and event.get('number') == number:
                                        event['status'] = 'acknowledged' if data['ack'] == 'ack' else 'rejected'
                                        break
                            elif not any(e.get('direction') == 'in' and e.get('source') == source and e.get('number') == number and e.get('text') == text and time.time()-e['time'] < 600 for e in state.events):
                                state.events.append({'id': secrets.token_hex(8), 'time': time.time(), 'direction': 'in', 'source': source, 'to': to, 'text': text, 'number': number, 'status': 'received', 'via': str(data.get('via', 'RF'))})
                            state.save()
                        else:
                            raise ValueError('Unknown event kind.')
                        self.reply({'ok': True})
                    else:
                        self.reply({'error': 'Not found.'}, 404)
                else:
                    self.reply({'error': 'Not found.'}, 404)
        except PermissionError as exc:
            self.reply({'error': str(exc)}, 403)
        except (ValueError, TypeError, KeyError) as exc:
            self.reply({'error': str(exc)}, 400)
        except OSError:
            self.reply({'error': 'Cannot save message history. Check folder permissions.'}, 500)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open', action='store_true', help='Open the station page in your browser')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    state = State(ROOT / 'messenger_history.json')
    server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    server.daemon_threads = True
    server.state = state
    addresses = set()
    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(('192.0.2.1', 9))
        addresses.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    server.phone_urls = ['http://'+ip+':'+str(args.port)+'/messenger' for ip in sorted(addresses) if not ip.startswith('127.')]
    print('\nPacket LAN messenger v0.13', flush=True)
    print('Station: http://localhost:'+str(args.port)+'/station', flush=True)
    for url in server.phone_urls:
        print('Phone:   '+url, flush=True)
    print('Pairing code: '+state.code+'\nKeep this window open. Ctrl+C stops the server.\n', flush=True)
    if args.open:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open('http://localhost:'+str(args.port)+'/station')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
