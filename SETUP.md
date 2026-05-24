# Setup Guide for Classmates

Welcome! This guide walks you through getting StudyBuddy running on your own laptop. It takes about 20 minutes the first time. You don't need to know how to code — just follow each step exactly.

**Important: your data stays on your own laptop. Nothing you do here is visible to anyone else, including the person who made this. Each person uses their own API keys and their own materials.**

---

## What you'll need

- A laptop (Mac, Windows, or Linux)
- A credit or debit card (for the AI service — we'll set a $25/month cap so there are no surprises)
- About $5-15 per month of API usage, depending on how much you study with it
- 20 minutes to set things up the first time

---

# Part 1: Install Python (5 minutes)

## On Mac

1. Open the **Terminal** app (press `Cmd + Space`, type "Terminal", press Enter)
2. Type this and press Enter:
   ```
   python3 --version
   ```
3. If you see `Python 3.10` or higher, skip to Part 2.
4. If not, go to https://www.python.org/downloads/ and click the big yellow download button. Open the downloaded `.pkg` file and click through the installer using all the defaults.
5. **Close Terminal and reopen it.** Then check the version again with the command above.

## On Windows

1. Go to https://www.python.org/downloads/ and click the big yellow download button.
2. **VERY IMPORTANT:** When you run the installer, check the box that says **"Add Python to PATH"** at the bottom of the first screen. If you forget this, Python won't work from the command line.
3. Click "Install Now" and let it finish.
4. Open **Command Prompt** (press the Windows key, type "cmd", press Enter)
5. Type `python --version` — you should see `Python 3.x.x`

> **Note for Windows users:** Throughout the rest of this guide, when I say "Terminal," you should use Command Prompt or PowerShell. Wherever I write `python3`, you'll type just `python` on Windows. Wherever I write `source venv/bin/activate`, you'll type `venv\Scripts\activate` instead.

---

# Part 2: Download StudyBuddy (3 minutes)

## Option A: Download from GitHub (easiest)

1. Go to the GitHub link your classmate shared
2. Click the green **"Code"** button
3. Click **"Download ZIP"**
4. Find the downloaded file in your Downloads folder and double-click it to unzip
5. You should now have a folder called `studybuddy-main` (or similar) in Downloads

## Option B: Using git (if you know how)

```
git clone <repo-url> studybuddy
```

---

# Part 3: Get your API key (5 minutes)

This is what powers the AI that builds your study guides. Each person needs their own.

1. Go to **https://console.anthropic.com**
2. Sign up with your email and verify it
3. Click the gear icon (Settings) in the sidebar
4. Click **Billing** → **Add payment method** → enter your card
5. **CRITICAL SAFETY STEP:** Click **Limits** in the Billing section. Set a **monthly spend limit of $25**.
   This is your safety net. If anything goes wrong, the most you can be charged is $25. You can always raise it later if you need to.
6. Click **API Keys** in the sidebar
7. Click **Create Key**, name it `studybuddy`, click Create
8. **A long key starting with `sk-ant-...` will appear.** Copy it and paste it into a Notes document. You will not see this key again after closing the window.

⚠️ **NEVER share this key with anyone.** It's literally a password that can spend your money. If you suspect it leaked, go back and delete it, then create a new one.

---

# Part 4: Set up the app (5 minutes)

Open Terminal (Mac) or Command Prompt (Windows). Type each command and press Enter. Wait for each to finish before doing the next.

### Step 1: Go into the studybuddy folder

**On Mac:**
```
cd ~/Downloads/studybuddy-main
```

**On Windows:**
```
cd %USERPROFILE%\Downloads\studybuddy-main
```

(Adjust `studybuddy-main` to whatever the folder is actually called.)

### Step 2: Create a virtual environment

**Mac:**
```
python3 -m venv venv
```

**Windows:**
```
python -m venv venv
```

Takes about 10 seconds. No output is normal.

### Step 3: Activate the environment

**Mac:**
```
source venv/bin/activate
```

**Windows:**
```
venv\Scripts\activate
```

Your prompt should now have `(venv)` at the front.

### Step 4: Install dependencies

```
pip install -r requirements.txt
```

This takes 1-2 minutes. You'll see lots of text scroll by — that's normal. Wait until your `(venv)` prompt comes back.

### Step 5: Set your API key

**Mac:**
```
export ANTHROPIC_API_KEY=paste-your-key-here
```

**Windows:**
```
set ANTHROPIC_API_KEY=paste-your-key-here
```

Replace `paste-your-key-here` with the actual key from your Notes document (no quotes needed).

### Step 6: Start the app

```
python cli.py serve
```

You should see:
```
🌱 StudyBuddy running at http://127.0.0.1:5000
```

### Step 7: Open it in your browser

Open Chrome or Safari and go to **http://127.0.0.1:5000**

🎉 You should see the StudyBuddy welcome screen.

---

# How to use it later (after the first setup)

Every time you want to study:

1. Open Terminal / Command Prompt
2. Go into the folder:
   - Mac: `cd ~/Downloads/studybuddy-main`
   - Windows: `cd %USERPROFILE%\Downloads\studybuddy-main`
3. Activate the environment:
   - Mac: `source venv/bin/activate`
   - Windows: `venv\Scripts\activate`
4. Set your key (if you didn't make it permanent):
   - Mac: `export ANTHROPIC_API_KEY=your-key`
   - Windows: `set ANTHROPIC_API_KEY=your-key`
5. Start: `python cli.py serve`
6. Open http://127.0.0.1:5000

To **stop the app**, press `Ctrl + C` in the Terminal window where it's running.

---

# Make your API key permanent (optional but recommended)

So you don't have to paste it every time.

**On Mac:** In Terminal, run:
```
nano ~/.zshrc
```
Scroll to the bottom using arrow keys. Add this line (with your real key):
```
export ANTHROPIC_API_KEY=your-actual-key-here
```
Press `Ctrl + O`, then Enter to save. Then `Ctrl + X` to exit. Close and reopen Terminal.

**On Windows:**
1. Press the Windows key, type "environment variables", click "Edit the system environment variables"
2. Click "Environment Variables..." button
3. Under "User variables", click "New"
4. Variable name: `ANTHROPIC_API_KEY`
5. Variable value: paste your key
6. OK out of all the dialogs
7. Close and reopen Command Prompt

---

# Common problems

**"python3: command not found" / "python is not recognized"**
Python isn't installed properly. On Windows, you probably forgot to check "Add Python to PATH" during install — uninstall Python and reinstall with that box checked.

**"No module named anthropic"**
Your venv isn't active. Run the activate command again (Step 3 above).

**"Port 5000 already in use"**
The app is already running in another Terminal window. Find it and stop it, OR start on a different port:
```
python cli.py serve --port 5001
```
Then visit http://127.0.0.1:5001 instead.

**Browser shows "can't connect" or "this site can't be reached"**
Make sure the Terminal window still shows the "running at..." message. If it's gone, the app stopped — restart it.

**"Authentication error" or "Invalid API key"**
Your API key isn't set correctly. Make sure you set it in this Terminal session (Step 5) and there are no quotes, no extra spaces.

**API key starts working then stops**
You probably hit your monthly limit. Go to console.anthropic.com → Billing → Limits and check.

---

# Cost guide

Each lecture costs about **$3-5** to fully study (initial generation + all the on-demand features):

- Generating a new lecture's reading materials: ~$1-2
- Each "Generate Quiz" / "Generate Flashcards" / etc. click: 5-15¢
- The comprehensive end-of-lecture quiz: 20-40¢

A full semester of heavy use is typically **$100-200**. If that scares you, set your limit at $25/month and just be selective about which features you use on which lectures.

---

# Privacy & responsibility

- Everything you do stays in `data/library.json` on **your** laptop. No one else can see it.
- The lecture content + your notes get sent to Anthropic's API (Claude) when you generate stuff. Their privacy policy: https://www.anthropic.com/legal/privacy
- If you upload video files for transcription, those go to OpenAI's API (Whisper).
- Don't share generated study materials publicly — the underlying lecture content isn't yours to redistribute.
- Check your school's policy on AI tools before relying on this.

---

# Getting help

Read the main README.md for more details on what each feature does. If you're stuck on setup, the person who shared this with you might be able to help — but they're also a student, so don't expect 24/7 IT support. Be patient.
