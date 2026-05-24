# How to Share StudyBuddy via GitHub

This is the guide for **you** (the owner) on how to put StudyBuddy on GitHub so classmates can download it. Once it's up there, you share one link and people self-serve.

---

## Step 1: Make a GitHub account (if you don't have one)

1. Go to https://github.com
2. Click "Sign up" and follow the prompts
3. Use your school email or personal email — doesn't matter

Tip: Pick a username you wouldn't mind classmates seeing.

---

## Step 2: Install Git on your Mac

Open Terminal and check if it's already there:

```
git --version
```

If you see a version number, you're good. If not:

```
xcode-select --install
```

A dialog will pop up — click "Install" and wait a few minutes.

---

## Step 3: Create a new repository on GitHub

1. Go to https://github.com and log in
2. Click the **+** icon in the top right → **New repository**
3. Repository name: `studybuddy` (or whatever you want)
4. Description: "Personal med school study tool"
5. Choose **Public** (so classmates can see and download it without permission) OR **Private** (only people you invite can see it)
   - For sharing with classmates, **Public** is easier
6. **DO NOT** check "Add a README" or "Add .gitignore" — we already have those
7. Click **Create repository**

You'll see a page with setup instructions. Keep this tab open — you'll need the URL from it.

---

## Step 4: Push your code to GitHub

In Terminal:

### Step 4a: Make sure you're in the studybuddy folder

```
cd ~/Downloads/studybuddy
```

### Step 4b: Initialize git

```
git init
```

### Step 4c: Verify your personal data is excluded

This is critical — you do NOT want to upload your study data, API keys, or your virtual environment.

```
cat .gitignore
```

You should see `data/library.json`, `venv/`, `.env`, etc. listed. If you don't, something's wrong — message me before continuing.

### Step 4d: Add all the files

```
git add .
```

### Step 4e: Double-check what's about to be uploaded

```
git status
```

Read the list of files. You should see code files (`.py`, `.html`, `.css`, `.js`), the README, SETUP.md, requirements.txt, etc.

**You should NOT see:**
- `data/library.json` ← your study data
- `venv/` ← your Python environment
- Any file containing API keys

If anything sensitive is listed, stop and message me.

### Step 4f: Tell git who you are (first time only)

```
git config --global user.email "your-email@example.com"
```

```
git config --global user.name "Your Name"
```

### Step 4g: Commit and push

```
git commit -m "Initial commit"
```

```
git branch -M main
```

Now look at the GitHub page you kept open. It shows commands like:
```
git remote add origin https://github.com/YOUR-USERNAME/studybuddy.git
git push -u origin main
```

Copy and paste those two commands into Terminal exactly as GitHub shows them.

GitHub will probably ask you to authenticate. The easiest method: it'll pop up a browser window for you to log in. If it asks for a password in Terminal, you actually need a **personal access token** instead:
1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Note: "studybuddy"
4. Expiration: 90 days is fine
5. Check the "repo" scope
6. Generate, copy the token, paste it in Terminal when prompted for password

---

## Step 5: Verify

Refresh your repository page on GitHub. You should see all your files listed.

**Click on `data/` if it's there** — if it's empty (or there's no `data/` folder at all), great. If you see `library.json` inside, that means it got uploaded by accident and you need to remove it — let me know.

---

## Step 6: Share with classmates

The link to share is just your repository URL:

```
https://github.com/YOUR-USERNAME/studybuddy
```

Send them this with a short note like:

> Hey! I built a med school study tool that turns lectures into interactive study guides. If you want to try it, here's the link — instructions for setup are in SETUP.md. You'll need your own Anthropic API key (instructions are in there). Costs ~$5/month for moderate use.
>
> Heads up: I'm not running tech support — if you get stuck I might help if I have time, but read SETUP.md carefully first.

---

## Updating later

When you change something and want to push the update:

```
cd ~/Downloads/studybuddy
git add .
git commit -m "Description of what changed"
git push
```

Classmates who already cloned the repo will need to pull updates:

```
git pull
```

(Or they just re-download the ZIP.)

---

## If you change your mind

You can delete the repo anytime:
1. Go to your repo on GitHub
2. Settings (top right of the repo page)
3. Scroll all the way to the bottom
4. "Delete this repository"

Anyone who downloaded the code already has their own copy, but the public link goes away.

---

## Privacy reminders

- ✅ Your `data/library.json` is gitignored — it won't be uploaded
- ✅ Your API keys aren't in any file — they live in Terminal environment variables
- ✅ Classmates each use their own keys and have their own private library
- ❌ Don't add commits where API keys appear in code, even temporarily
- ❌ Don't push if `git status` shows your library.json

If you accidentally push a key, immediately:
1. Delete the key in the Anthropic console
2. Create a new one
3. Remove the file from git history (or just delete the whole repo and start over)
