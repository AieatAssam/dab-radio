# Install a release package

DAB Radio packages target **Debian 13 (Trixie)** and **64-bit Raspberry Pi OS Trixie**, on `arm64` and `amd64`. They are not intended for 32-bit systems. Check the [GitHub Releases page](https://github.com/AieatAssam/dab-radio/releases/latest) for available packages.

## Download and install

On a supported system, download the package matching its architecture. For a 64-bit ARM host:

```bash
gh release download --repo AieatAssam/dab-radio --pattern '*_arm64.deb'
sudo apt install ./dab-radio_*_arm64.deb
```

For an `amd64` host, use the matching `*_amd64.deb` artifact and filename. Alternatively download the appropriate `.deb` from the [latest release](https://github.com/AieatAssam/dab-radio/releases/latest) in a browser, then install it with `sudo apt install ./<package-file>.deb`.

Packages bundle the decoder and Python runtime dependencies. Installation does not compile source on the target or download Python packages with pip. `apt` may fetch operating-system libraries from configured Debian repositories.

## Configure the receiver

The service runs as the dedicated `dab-radio` user. Package paths are:

| Purpose | Path |
| --- | --- |
| Application | `/opt/dab-radio` |
| Runtime state | `/var/lib/dab-radio` |
| Configuration | `/etc/dab-radio/dab-radio.conf` |

Configure the RTL-SDR device and runtime options in `/etc/dab-radio/dab-radio.conf`. Ensure the system's udev rules and device permissions allow the service user to access the tuner. Then enable and start the service:

```bash
sudo systemctl enable --now dab-radio.service
sudo systemctl status dab-radio.service
```

Open `http://<host>:8090` from a browser on the same network. Use the machine's hostname or address in place of `<host>`. Port 8080 is not used; the service listens on 8090.

The app requires a browser with JavaScript and audio support. Native pinned mini-player mode requires a supporting desktop browser and HTTPS or localhost. On an ordinary LAN HTTP address, use the main player; for localhost access from another computer, an SSH tunnel can provide a secure browser context:

```bash
ssh -N -L 18090:127.0.0.1:8090 <user>@<host>
```

Visit `http://localhost:18090` in the browser. Leave the tunnel open while using the mini-player.

## Service operations

```bash
sudo systemctl status dab-radio.service
sudo journalctl -u dab-radio.service -f
sudo systemctl restart dab-radio.service
sudo systemctl stop dab-radio.service
```

A single physical tuner receives one multiplex at a time. Scanning interrupts reception. Reception quality depends on the antenna, location, interference and device; receiver errors and missing RF audio cannot be eliminated or recovered by the software.

## Existing source checkout

Package installation does not migrate an existing source checkout, service account, or runtime state. Treat an existing checkout deployment separately when planning a migration.

For development installation, build and deployment details are in the repository README and [decoder patch notes](../patches/README.md). The package workflow is documented in [RELEASING.md](RELEASING.md).
