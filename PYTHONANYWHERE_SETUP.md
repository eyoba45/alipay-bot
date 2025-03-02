
# PythonAnywhere Deployment Guide

Follow these steps to deploy your Telegram bot on PythonAnywhere:

## 1. Create a PythonAnywhere Account

- Go to [PythonAnywhere.com](https://www.pythonanywhere.com/) and sign up for an account
- Free accounts work for basic bots, but paid accounts offer better performance

## 2. Upload Your Files

### Using GitHub:
- Push your code to GitHub
- In PythonAnywhere, open a Bash console
- Clone your repository:
  ```
  git clone https://github.com/your-username/your-repo.git
  ```

### Manual Upload:
- Compress your files into a ZIP archive
- In PythonAnywhere, go to Files and upload the ZIP
- Open a Bash console and unzip:
  ```
  unzip yourfile.zip -d your-bot-folder
  cd your-bot-folder
  ```

## 3. Set Up Environment Variables

- Go to the Dashboard and click on the Web tab
- Under "Environment variables", add:
  - TELEGRAM_BOT_TOKEN = your_token_here
  - ADMIN_CHAT_ID = your_admin_id_here

## 4. Install Requirements

- Open a Bash console and navigate to your project folder
- Install the dependencies:
  ```
  pip3 install --user -r requirements.txt
  ```

## 5. Configure Web App

- Go to the Web tab
- Click "Add a new web app"
- Choose "Manual configuration" and select Python 3.9
- Set the WSGI configuration file to point to your wsgi.py
- In the "Code" section, set the path to your project folder

## 6. Additional Setup

- Set up an Always-On task to run your bot.py file
- Go to the Tasks tab and create a scheduled task:
  ```
  python /home/yourusername/your-project/bot.py
  ```
- Set it to run daily

## 7. Checking Logs

- Check the error logs if your bot doesn't work:
  - Web app logs under the Web tab
  - Your bot's log file: bot_uptime.log

## 8. Restart Your Web App

- After making changes, always restart your web app from the Web tab
