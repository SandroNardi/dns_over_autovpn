# Auto VPN DNS inventory

A local, read-only web page for one Meraki organization. The server listens on `127.0.0.1` only. For every appliance network it reports:

- **Auto VPN role:** Hub, Spoke, Off, or Error.
- **Hubs for each spoke:** in configured order, which is their priority, with the default-route flag. Tunnel status is optional for each scan.
- **MX VLAN 1 (spokes):** the DHCP mode and the DNS servers handed out.
- **Switches (spokes):** whether any switch or stack routes at Layer 3, whether VLAN 1 has a Layer 3 interface, and that interface's DHCP mode and DNS servers.

The page can search, filter, sort, and expand a row, and it can export the full scan as CSV. While a scan runs, the terminal prints one line per network and the page shows a progress bar.

## Important notice

This project is provided **as is**, without warranty of any kind, as stated in the [MIT License](LICENSE). It is intended for lab, educational, and evaluation use, and as an example to learn from.

- It is not production software. It is not suitable for production environments and is not supported.
- Test it in your own environment and adapt it to your requirements and security policies before relying on it for anything.
- Use a read-only Dashboard API key, and only with organizations you are authorized to access.
- The authors and contributors are not liable for any damage, data loss, service disruption, or other consequences of using or misusing this project.

## Requirements

- Python 3.11 or newer. Meraki Dashboard SDK 4.x requires Python 3.11 or newer. Tested on Python 3.14 on Windows.
- Git, or a ZIP download of this repository.
- Outbound HTTPS from this computer to `api.meraki.com`.
- A Dashboard API key created by an administrator with read-only access to the organization. A Dashboard API key is 40 hexadecimal characters.
- API access enabled on that organization.

## Install

The app runs from source. `pyproject.toml` records the name, version, Python requirement, and pytest settings. Install dependencies from the requirements files. `pip install .` is not the install step.

Clone the repository and enter it:

```bash
git clone <repository-url>
cd dns_over_autovpn
```

You can download the repository as a ZIP instead. Unpack it and open a terminal in that folder.

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Activation is optional. To activate: `.\.venv\Scripts\Activate.ps1`. The commands below call `.\.venv\Scripts\python.exe` directly.

### macOS and Linux

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Activation is optional. To activate: `source .venv/bin/activate`. The commands below call `./.venv/bin/python` directly.

`requirements.txt` installs `meraki` (1.46.0 or newer) and `rich` (13.0.0 or newer).

## Set up the API key

Use a **read-only** Dashboard API key, created by an administrator with read-only organization access. The app also blocks every Dashboard call that is not a read, but the key's privileges are the main safeguard.

The server reads the key from the environment variable `MK_CSM_KEY`. If that variable is missing or empty, the page takes one paste and holds it in process memory until the server stops. The paste is not written to the environment.

A non-empty `MK_CSM_KEY` is passed through as stored. This path does not check the 40-character shape before the first Dashboard call. When the variable is set, the page does not show the paste form, including when the stored value cannot be used.

### Windows

Save the key as a user environment variable named `MK_CSM_KEY`. This PowerShell snippet keeps the key out of your shell history:

```powershell
$k = Read-Host "Meraki read-only API key" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($k))
[Environment]::SetEnvironmentVariable("MK_CSM_KEY", $plain, "User")
Remove-Variable k, plain
```

You can also set it from **System Properties > Environment Variables > User variables > New**. Name the variable `MK_CSM_KEY`.

User variables only reach programs started afterwards. Restart your terminal or IDE. To check it is set without printing it, run `[bool]$env:MK_CSM_KEY`, which should return `True`.

To remove a saved environment variable later, run `[Environment]::SetEnvironmentVariable("MK_CSM_KEY", $null, "User")`, then restart your terminal or IDE.

### macOS and Linux

For this terminal only, type the key and press Enter. The characters are not echoed. Programs started from this terminal can see the variable; it goes away when the terminal closes.

```bash
read -rs MK_CSM_KEY && export MK_CSM_KEY
```

To have new terminals pick it up, export `MK_CSM_KEY` from your shell profile (`~/.zshrc` or `~/.bashrc`). A profile line stores the key as plaintext on disk. Prefer a secret manager or the system keychain, and export `MK_CSM_KEY` from there when the shell starts.

To check it is set without printing it:

```bash
[ -n "$MK_CSM_KEY" ] && echo set
```

That prints `set` when the variable is non-empty.

### Paste the key in the page

If `MK_CSM_KEY` is not set, the page asks you to paste a read-only key and select **Use key for this run**. The server accepts the paste only when the value, after trimming whitespace, is exactly 40 hexadecimal characters. Anything else is refused and is not saved.

That key is held in the server process until you stop it. The app does not write it to a file, the log, the environment, or browser storage. It is sent once to `127.0.0.1` only. Decline if the browser offers to save it. Stopping the server drops it. A password manager, or the browser's developer tools during the paste, can still keep a copy outside this app.

The server keeps one key for the life of the process. It will not take a second paste over a key from the environment or from an earlier paste.

## Launch

From the project directory.

Windows:

```powershell
.\.venv\Scripts\python.exe server.py
```

macOS and Linux:

```bash
./.venv/bin/python server.py
```

The server binds `127.0.0.1`. It starts at port 8772 and, if that port is taken, tries each later port through 8821. The terminal prints the URL that bound, for example:

```text
Auto VPN DNS inventory at http://127.0.0.1:8772/
Press Ctrl+C to stop.
```

It then opens that URL in your browser. If it skipped busy ports, it names those ports and the port it is using. If `MK_CSM_KEY` is not set, it warns that the page will ask for a key and keep it in memory until you stop the server.

Leave the terminal open. Press Ctrl+C to stop.

## Command-line options

| Option | What it does |
| --- | --- |
| *(none)* | Try `127.0.0.1` ports 8772 through 8821 and listen on the first free port. Open the browser. |
| `--port N` | Port to try first. `N` is an integer from 1024 to 65535. A port inside 8772–8821 is tried first, then the rest of that band. A port outside the band is tried once. An invalid port prints an error and exits with code 2. |
| `--no-browser` | Do not open the browser. The terminal still prints the URL. |

If every tried port is in use, the process prints `Port ... is in use` (or `Ports ... are in use`) and exits with code 1. Any other bind failure also exits with code 1. After you stop a running server with Ctrl+C, the process exits with code 0.

Windows:

```powershell
.\.venv\Scripts\python.exe server.py --port 8780
```

macOS and Linux:

```bash
./.venv/bin/python server.py --port 8780 --no-browser
```

## Using the page

1. Choose an organization. If the key can see only one, it is already selected.
2. Leave **Include tunnel status** unchecked, or turn it on. Checked means one extra organization-wide read of tunnel status for this scan.
3. Select **Scan organization**. The page shows a progress bar. The terminal prints one line per network, then a summary (networks, spokes, hubs, API calls, elapsed time). One network failing does not stop the scan.
4. Search by network, hub, DNS server, or note. Filter with Auto VPN role, hub, MX VLAN 1, switch Layer 3, switch VLAN 1 DHCP, and **Only rows with notes**. The summary chips apply those filters. **Reset filters** clears them.
5. Click a column header to sort. Click a row for details: hubs in priority order, MX VLAN 1, switch Layer 3 interfaces, and notes.
6. Select **Export full CSV**. The file contains every row from the scan, including rows hidden by the current filters. The name is `autovpn-dns-inventory-<organization id>.csv`.

## What the columns mean

### MX VLAN 1

| Status | Meaning |
|---|---|
| DHCP server | The MX serves DHCP on VLAN 1. DNS shows the custom list in order, a preset (upstream, Google, Umbrella/OpenDNS), or Not set. |
| DHCP relay | The MX relays DHCP. DNS comes from the relay target, which the Dashboard cannot see. |
| DHCP disabled | The MX does not answer DHCP on VLAN 1. |
| VLAN 1 not configured | VLANs are enabled, but VLAN 1 does not exist. |
| VLANs disabled (single LAN) | The MX uses one LAN. The API returns the subnet but not the DHCP DNS list. |
| Passthrough mode (no MX LAN) | The MX has no LAN and no DHCP. |
| Read error | The API returned an error. See Notes. |

Hubs, networks with Auto VPN off, and networks whose Auto VPN read failed show **Not checked**.

### Switches

| Switch L3 | Meaning |
|---|---|
| Yes | At least one switch or stack has a Layer 3 interface. |
| No | Switches exist and none has a Layer 3 interface. |
| No switches | The network has no switches. |
| Unknown | Routing interfaces could not be read. See Notes. |

**Switch VLAN 1** names the switch or stack that owns the VLAN 1 interface. Other values:

- **No VLAN 1 interface:** the switches route, but not on VLAN 1.
- **None:** the switches do not route at all.
- **Multiple (N):** more than one VLAN 1 interface exists. Each is listed in the row details.

Stack members are counted once, under the stack. **Notes** also flags DHCP option 6, which can override the DNS list clients receive, and networks bound to a configuration template.

## Dashboard API calls

Every call is a GET.

| Call | When |
|---|---|
| `getOrganizations` | Once, for the organization list |
| `getOrganizationNetworks` (appliance) | Once per scan |
| `getOrganizationDevices` (switch) | Once per scan |
| `getOrganizationConfigTemplates` | Once per scan, for template names |
| `getOrganizationApplianceVpnStatuses` | Once per scan, only when tunnel status is turned on |
| `getNetworkApplianceVpnSiteToSiteVpn` | Every appliance network |
| `getNetworkApplianceVlan` (VLAN 1) | Every spoke |
| `getNetworkApplianceSettings`, `getNetworkApplianceVlansSettings`, `getNetworkApplianceSingleLan` | Only when VLAN 1 cannot be read, to tell passthrough, single LAN, and a missing VLAN 1 apart |
| `getNetworkSwitchStacks` | Spokes with switches |
| `getNetworkSwitchStackRoutingInterfaces`, `getDeviceSwitchRoutingInterfaces` | Each stack and each standalone switch |
| `getNetworkSwitchStackRoutingInterfaceDhcp`, `getDeviceSwitchRoutingInterfaceDhcp` | Only for VLAN 1 interfaces |

## Logs

`application.log` is appended in the folder you launch from (the current working directory). The terminal shows the same events with Rich formatting. The file is plain text, at INFO and above. `.gitignore` ignores `*.log`, so this file is not committed. The API key is never written to it. The Meraki SDK console log and SDK log file are turned off (`suppress_logging`, `print_console`, and `output_log`).

## Troubleshooting

**The key is not detected.** A user environment variable reaches programs started after it was saved. Restart your terminal or IDE, then start the server again. On Windows, `[bool]$env:MK_CSM_KEY` should return `True` in that new session. On macOS or Linux, `[ -n "$MK_CSM_KEY" ] && echo set` should print `set`.

**`Port ... is in use`.** Every port the server tried is taken. Start again with `--port` and a free port from 1024 to 65535. A port outside 8772–8821 is tried once. A port inside that band is tried first, then the rest of the band.

**`Could not list organizations. Check the API key and network access.`** The key is wrong, Dashboard API access is disabled on the organization, or a proxy or firewall is blocking HTTPS to `api.meraki.com`.

**A large organization is slow.** The Dashboard rate-limits requests, and the SDK retries them. This app sets `maximum_retries` to 5. The progress bar and the terminal advance one network at a time. The scan keeps going when a single network fails.

**The browser did not open.** Copy the URL the terminal printed (`http://127.0.0.1:<port>/`). Start with `--no-browser` when you want that behavior every time.

**Windows says `python` was not found.** Use the `py` launcher and the virtual environment interpreter, for example `py -3 -m venv .venv` and `.\.venv\Scripts\python.exe server.py`.

## Run the tests

Install the development requirements (they include `requirements.txt` and add pytest), then run pytest from the project directory. The suite is 40 tests. They use fakes and do not call the Dashboard.

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

macOS and Linux:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest -q
```

## Security notes

- The server binds `127.0.0.1` only. It answers a request only when the Host header is `127.0.0.1` or `localhost` on the bound port. A POST must carry this page's own Origin. A cross-site request is rejected.
- Dashboard calls go through a wrapper. It allows `get` methods on the organizations, appliance, and switch sections and blocks every other method. The calls listed above are GETs.
- The read-only privilege on the API key is the main safeguard. The method block is a backstop inside this process.
- The key is not returned to the browser, not written to `application.log`, and not stored in the project. A pasted key stays in process memory until the process exits, and it is not copied into the environment.
- In the CSV export, a cell that starts with `=`, `+`, `-`, `@`, a tab, or a carriage return is prefixed with a single quote so a spreadsheet does not treat it as a formula.

## License

MIT License. Copyright (c) 2026 Sandro Nardi. See [LICENSE](LICENSE).
