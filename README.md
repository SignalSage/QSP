# QSP

A custom browser amateur radio FX.25 packet messenger geared for third party traffic using local IP - Most browser devices compatable!

QSP v0.13

GET STARTED ON WINDOWS
1. Extract this entire ZIP into a folder. Python 3.9 or newer is required;
   no extra Python packages are needed.
2. Double-click start_station.bat. Keep its terminal window open.
   Alternatively run: py -3 station_server.py --open
3. The station opens at http://localhost:8765/station on the radio computer.
   Use this served page instead of double-clicking the HTML file. Localhost
   lets the browser request microphone access.
4. Set Station callsign (for example AA1O-1), modem tones/baud, and the RF TX
   composer's Path. Start microphone RX, select the radio audio output in
   Windows, and configure your radio's VOX/audio interface as usual.
5. Check "Allow paired LAN devices to send radio messages". Audio is unlocked
   by this click. The phone addresses and pairing code appear below it.
6. Put the iPhone/tablet/computer on the same LAN or Wi-Fi. Open the displayed
   http://192.168.x.x:8765/messenger address in Safari or another browser.
   Enter the pairing code, then a destination callsign-SSID and a message.
7. The other radio station replies to YOUR Station callsign-SSID, e.g. AA1O-1.
   Decoded, CRC-valid RF messages addressed there appear in the conversation.

You can make a shortcut to the phone URL on its Home Screen. Internet access
is not required for LAN messaging or RF operation. APRS-IS remains optional.

WHAT THE MESSAGE STATUS MEANS
Waiting for station: request is pending while audio/test playback is busy.
Transmitting: the station is playing the packet audio.
Audio sent / delivery unconfirmed: playback finished. This does not prove
VOX keyed the radio or that a receiving station heard it.
Acknowledged: the station decoded a matching APRS RF acknowledgement from
that destination. No automatic outgoing-message retries are performed.
Incoming numbered messages get one automatic RF acknowledgement when audio
is available (checkbox configurable). If another transmission interrupts
message audio, the UI reports the failure/unknown delivery.

Messages are standard AX.25/APRS text: up to 67 printable ASCII characters.
Emoji, non-ASCII text, |, ~, and { are unsupported. ack/rej prefixes are
reserved for protocol replies. Current FX.25 and modem settings apply.
All connected devices share the station's callsign and conversations. Devices
cannot choose a different sender callsign or issue arbitrary computer commands.
The phone is a messenger interface, not its own radio decoder.

SAVING AND STOPPING
Message history is stored in messenger_history.json beside the server. New
history is shared with paired devices. After a server restart, pair again;
unfinished transmissions are marked interrupted and never replayed.
Station-heard history still saves in browser storage and supports .txt backups.
Opening the served station page creates a different browser storage origin
from a double-clicked HTML file: import your heard .txt backup to bring it over.
Only one station tab can control the bridge at a time.
Turn the sharing checkbox off to cancel waiting device requests. It does not
cut off a message already playing; use Stop audio TX to stop playback. Closing
the page or losing its heartbeat disables new sends after 12 seconds and
cancels waiting requests. Leave the station computer/tab awake for operation.

CONNECTION TROUBLESHOOTING
If Windows asks about its firewall, allow Python on your PRIVATE network.
Phone access requires devices to be on a network that permits device-to-device
connections. Guest Wi-Fi/client isolation can prevent this. Phone cellular-only
access won't reach a private LAN address. No port forwarding is needed.
If there are multiple displayed addresses, use the one matching your Wi-Fi LAN.
To choose another port: py -3 station_server.py --port 8766 --open
If another station tab owns the bridge, disable it there or close it and wait
12 seconds before enabling the new tab.

FILES
station_server.py                       Local HTTP server / bridge
custom_packet_browser_v0.13.html         Radio station page
messenger.html                          Phone messenger page
start_station.bat                        Windows launcher
README.txt                              These instructions

This server is intended for your trusted private LAN. Pairing restricts who can
submit requests, but the local HTTP connection is not encrypted. Do not expose
this server through internet port forwarding. Keep the pairing code with the
people you want to use the station. The operator enables radio sharing and
controls the station's operating configuration.
