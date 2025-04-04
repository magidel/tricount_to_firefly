# Tricount to Firefly III

## Import Your Tricount Expenses with Categories Directly into Firefly III

### About This Tool

This tool extends the functionality of [Tricount Downloader](https://github.com/MrNachoX/tricount-downloader) by adding support for retrieving **expense categories**. Additionally, it enables seamless transfer of Tricount data to a local instance of [Firefly III](https://github.com/firefly-iii/firefly-iii) running on an LXC container in Proxmox.

Tricount is a popular expense-sharing app, but it lacks direct integration with personal finance managers like Firefly III. This script bridges the gap by automatically importing Tricount expenses into FireFly III, including category preservation and duplicate prevention.

---

## How It Works

### 1. Get Your Tricount URL

Open your Tricount in a web browser and copy the URL from the address bar:

```
https://tricount.com/XXXXXXXXXX
```

### 2. Configure Firefly III Access

You'll need your Firefly III host URL and a **personal access token**.

**Generate a token in Firefly III:**

- Navigate to: **Options → Profile → OAuth**
- Generate a new personal access token

### 3. Run the Script

Execute the script with the required parameters:

```
python tricount_to_firefly.py --tricount-key XXXXXXXXXX --firefly-host http://your-firefly-host --firefly-token your-token
```

### 4. Smart Synchronization

The script automatically:\
✅ Downloads expenses from Tricount with categories\
✅ Connects to your Firefly III instance\
✅ Checks for previously imported transactions\
✅ Only imports new transactions\
✅ Tracks imported transactions to prevent duplicates

### 5. Configuration Options

The script supports the following parameters into python file:

- \`DEFAULT_TRICOUNT_KEY\` - Your Tricount identifier.
- \`DEFAULT_FIREFLY_HOST\` - Your Firefly III URL.
- \`DEFAULT_FIREFLY_TOKEN\` - Your personal access token.
- \`DEFAULT_ACCOUNT_ID\` - Your account ID on FireFly (use "none" to automatically recover the first available account)
- \`DEFAULT_DAYS_RANGE\` - Number of days to check for duplicates (default: 180).

### 6. Automate with Cron (Optional)

You can schedule automatic imports using `crontab` on your Firefly III LXC instance. Example:

```
0 * * * * /bin/bash -c "cd /home/user/tricount-firefly/ && source /home/user/tricount-firefly/venv/bin/activate && python3 /home/user/tricount-firefly/tricount-to-firefly.py --no-excel >> /home/user/tricount-firefly/logfile.log 2>&1"
```

This runs the script every hour and logs the results.

---

## Installation Guide

### Prerequisites

Ensure you have the following installed:\
✅ **Python 3.6+** (download from [python.org](https://www.python.org/))\
✅ **A Firefly III instance** (running locally or on a server)

### Installation Steps

1️⃣ **Download the script**\
2️⃣ **Open a terminal and navigate to the script folder:**

```
cd path/to/download/folder
```

3️⃣ **Create and activate a virtual environment:**

```
python -m venv venv
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows
```

4️⃣ **Install required packages:**

```
pip install requests pandas rsa tqdm beautifulsoup4 openpyxl
```

5️⃣ **Run the script:**

```
python tricount_to_firefly.py --tricount-key XXXXXXXXXX --firefly-host http://your-firefly-host --firefly-token your-token
```

6️⃣ **Verify imported transactions** in your Firefly III instance.

7️⃣ **Deactivate the virtual environment (when finished):**

```
deactivate
```

---

## Advanced Usage

The script supports additional options for customization:

```
--tricount-key    Specify your Tricount key (the part after tricount.com/ in the URL)
--firefly-host    Specify your Firefly III host URL
--firefly-token   Provide your Firefly III personal access token
--days-range      Set the number of days to check for duplicates (default: 180)
--no-excel        Skip exporting transactions to an Excel file
```

### Full Example with All Parameters:

```
python tricount_to_firefly.py --tricount-key XXXXXXXXXX --firefly-host http://192.168.1.100 --firefly-token abcdef123456 --days-range 90 --no-excel
```

### Cron use

You can use the command

```
crontab -e
```

to automate export from Tricount and import to FireFly of new data.\
Here is an example of automation from 10.00 to 22.00 every 2 hours

```
0 10-22/2 * * * /bin/bash -c "cd /home/user/tricount-firefly/ && source /home/user/tricount-firefly/venv/bin/activate && python3 /home/user/tricount-firefly/tricount-to-firefly-grok.py --no-excel >> /home/user/tricount-firefly/logfile.log 2>&1
```


---

## License

This project is open-source and available under the MIT License.

---

## Contributing

Pull requests and suggestions are welcome! Feel free to submit issues for any bugs or feature requests.
