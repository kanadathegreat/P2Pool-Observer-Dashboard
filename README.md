# P2Pool-Observer-Dashboard

This is a Dashboard GUI for tracking P2Pool network and individual wallet metrics. There are no binary blobs so all code can be examined. It was built and tested on Linux Mint 22 and should work on the Debian family of distros with minimal fuss, though more dependencies may need to be installed.

## Features

- Live-updating Network and Wallet panels -- most numbers update the moment something happens on P2Pool, not on a delay
- Supports all three P2Pool networks: Normal, Mini, and Nano
- Track a specific wallet address, with saved wallets remembered for next time
- Built-in XMR price converter (USD, GBP, EUR)
- In-app Help screen explaining every number on the dashboard

## How to Setup (Linux / Ubuntu / Mint)

This project requires a Python virtual environment to manage dependencies safely and avoid "externally-managed-environment" errors.

### 1. Clone the repository
Open your terminal and download the project:
```bash
git clone https://github.com/kanadathegreat/P2Pool-Observer-Dashboard
cd P2Pool-Observer-Dashboard
```

### 2. Install system dependencies

Depending on your installation, you may need the Python virtual environment tool and a specific cursor library for the user interface. Run this to ensure you have them:

```bash
sudo apt update
sudo apt install python3-venv libxcb-cursor0
```

### 3. Create and activate a virtual environment (Extremely Important)

Set up an isolated Python environment inside the project folder:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install project requirements

With the virtual environment active, install the necessary Python packages:
```bash
pip install -r requirements.txt
```

### 5. Launch the Dashboard

The dashboard uses a custom launch script (`launch.sh`) that automatically handles the virtual environment for you.

First, make the script executable (you only need to do this once):
```bash
chmod +x launch.sh
```
To run the program:

- **Desktop:** Simply double-click `launch.sh` from your file manager.
- **Terminal:** Run `./launch.sh` while inside the project folder.

Note: Because `launch.sh` calls the virtual environment's Python binary directly, you do not need to run `source venv/bin/activate` every time you want to open the dashboard.

If you want to make it feel more like a program and you're running Linux Mint you can add a launcher shortcut to the desktop.

1. Simply right click on the desktop and select "Create New Launcher Here"
2. Give it a name.
3. Point the icon setting at the logo in the project's `assets` folder.
4. Hit browse and navigate to the project folder and select `launch.sh`.
5. You do not need to tick the "Launch in Terminal?" option.
6. When you hit OK it will ask you if you want an entry in the start menu. You can hit yes or no there, but I would go with yes so it shows up in the application search bar.

## License

Licensed under the MIT License with the Commons Clause condition attached -- free to use, modify, and share, but not to sell. See the `LICENSE` file for the full text.

## Support Development

If you find this dashboard useful and would like to sponsor continued development, please consider donating Monero (XMR).

Monero (XMR) Wallet ID:
```
49bry3cF6wi4zr1T35e29NWTqzc8Y4wQeGLUisc2jQFEe52LGP5Eu3vca1onXVZNikjXUDFiqVqLcY6A3zs4FMMf5StP3EU
```
