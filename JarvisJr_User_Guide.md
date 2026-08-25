
JarvisJr, Personal AI Agent
A Proof-of-Concept AI Assistant with Real-World Integration Capabilities

Project Report and User Setup Guide
Version: 1.0  |  Platform: Windows  |  Status: Proof of Concept


---


TABLE OF CONTENTS

1. Introduction
2. What Can JarvisJr Do?
3. System Requirements
4. Installation Guide
   Step 1:  Install Python
   Step 2:  Install Node.js
   Step 3:  Install Ollama and Download a Language Model
   Step 4:  Install Go (Required for WhatsApp)
   Step 5:  Clone the JarvisJr Repository
   Step 6:  Set Up the Python Environment for JarvisJr
   Step 7:  Configure Your Settings
   Step 8:  Set Up WhatsApp
   Step 9:  Run JarvisJr
5. Features in Detail
   5.1  WhatsApp Integration
    5.2  Memory — Jarvis Remembers You
    5.3  Web Browsing with Playwright
    5.4  File System Access
6. Architecture Overview
7. Known Limitations and Disclaimers
8. Credits


---


1. INTRODUCTION

JarvisJr is a personal AI assistant built as a Proof of Concept (POC) to demonstrate what a locally-running intelligent agent can do when connected to real-world services. Unlike cloud-based AI chat tools that only respond with text, JarvisJr can take action — it can read and send your WhatsApp messages, remember important things you tell it, browse the web, and manage files on your computer.

JarvisJr is powered by large language models (LLMs) running through Ollama, a free tool that lets you run powerful AI models on your own machine without sending your data to external servers. Communication between JarvisJr and the real-world services is handled through a framework called the Model Context Protocol (MCP), which gives Jarvis a clean and structured way to call external tools and services.

This document serves a dual purpose: it is both a technical project report for stakeholders who want to understand what has been built, and a step-by-step setup guide for someone installing and running JarvisJr for the first time on a Windows computer.

Note: JarvisJr is a Proof of Concept. It is not a finished product. Some features are still experimental and are documented as such.


---


2. WHAT CAN JARVISJR DO?

At its core, JarvisJr is a conversational AI agent. You type messages to it in a terminal window, and it responds in plain English. However, unlike a basic chatbot, JarvisJr can also call upon a set of real-world tools on your behalf.

Here is a high-level summary of its current capabilities:

- WhatsApp Integration: Jarvis can search your contacts, list your chats, read messages, and send WhatsApp messages directly from the terminal. This is the flagship feature of this POC.

- Persistent Memory: Jarvis can remember facts, names, preferences, and notes you share with it. These memories are stored locally and persist across sessions.

- Web Browsing: Jarvis can open a browser, navigate to websites, read page content, and interact with web elements — all on your behalf.

- File System Access: Jarvis can read and write files within a designated safe folder on your computer.

All of this happens locally on your machine. Your conversations and data are not sent to any third-party cloud server.

[SCREENSHOT PLACEHOLDER: A terminal window showing Jarvis responding to a user request, with multiple MCP server tools listed as "connected" in the startup banner.]


---


3. SYSTEM REQUIREMENTS

Before you begin installation, please ensure your Windows computer meets the following requirements.

Software Requirements:

- Operating System: Windows 10 or Windows 11 (64-bit)
- Python: Version 3.11 or higher
- Node.js: Version 18 or higher
- Go: Version 1.21 or higher (required for the WhatsApp bridge component)
- Ollama: Latest version
- Git: For cloning the repository
- Internet connection: Required during installation and for WhatsApp connectivity

Hardware Recommendations:

- RAM: At least 8 GB (16 GB recommended if running larger AI models locally)
- Storage: At least 10 GB of free space (AI models can be several gigabytes each)
- CPU: Modern multi-core processor

If you intend to use the recommended cloud-based AI model (gpt-oss:120b-cloud), the hardware requirements are significantly relaxed since the heavy processing happens on a remote server. A basic modern laptop will be sufficient.


---


4. INSTALLATION GUIDE

This section walks you through the complete installation process, step by step. Take your time with each step and do not skip ahead. If a step asks you to open a new terminal window, do so in addition to keeping any existing windows open.

Throughout this guide, when you see text inside a box like this:

    python --version

...it means you should type or paste that exact text into your terminal (Command Prompt or PowerShell) and press Enter.


STEP 1: INSTALL PYTHON

Python is the primary programming language that JarvisJr is written in.

1. Open your web browser and go to: https://www.python.org/downloads/
2. Click the large yellow "Download Python 3.x.x" button (the exact version number will vary).
3. Run the downloaded installer.
4. IMPORTANT: On the first screen of the installer, check the box that says "Add Python to PATH" before clicking Install Now.
5. Click "Install Now" and wait for the installation to complete.
6. Click "Close" when done.

To verify Python installed correctly, open a new Command Prompt (search "cmd" in the Start Menu) and type:

    python --version

You should see something like: Python 3.11.9

[SCREENSHOT PLACEHOLDER: The Python installer window with the "Add Python to PATH" checkbox highlighted.]


STEP 2: INSTALL NODE.JS

Node.js is required to run several of the MCP plugin servers that JarvisJr uses (for Memory, Filesystem, and Playwright).

1. Open your web browser and go to: https://nodejs.org/
2. Click the "LTS" (Long Term Support) download button. This is the stable, recommended version.
3. Run the downloaded installer and follow the default prompts — you do not need to change any settings.
4. When asked about "Tools for Native Modules", you can leave this unchecked unless you know you need it.
5. Click "Finish" when done.

To verify Node.js installed correctly, open a new Command Prompt and type:

    node --version

You should see something like: v20.11.0

[SCREENSHOT PLACEHOLDER: The Node.js website with the LTS download button visible.]


STEP 3: INSTALL OLLAMA AND DOWNLOAD AN AI MODEL

Ollama is the tool that runs the AI brain behind JarvisJr. It lets you download and run large language models locally.

3a. Install Ollama

1. Go to: https://ollama.com/download
2. Click "Download for Windows".
3. Run the installer and follow the prompts.
4. Ollama will start automatically in the background after installation. You will see an Ollama icon appear in your system tray (bottom-right of the taskbar).

To verify Ollama installed correctly, open a new Command Prompt and type:

    ollama --version

3b. Download an AI Model

Jarvis needs a language model to think and respond. We recommend the following:

- Best Experience (requires a network connection to a model server):
    gpt-oss:120b-cloud
  This is a large, high-quality model hosted on a dedicated server. It gives the most natural and capable responses.

- Cost-Effective Alternatives (runs fully on your machine):
  For computers with less memory or for offline use, you can use a smaller local model:
    ollama pull llama3:8b
  or
    ollama pull qwen2.5:14b

To download the cloud model, open a Command Prompt and type:

    ollama pull gpt-oss:120b-cloud

Wait for the download to complete. This may take several minutes depending on your internet speed.

Note: If you are using the local alternatives, the model will download directly to your machine. The 8B model is approximately 4.7 GB and the 14B model is approximately 8 GB.


STEP 4: INSTALL GO (REQUIRED FOR WHATSAPP)

Go is a programming language used to power the WhatsApp bridge component. The bridge is what lets JarvisJr talk to WhatsApp on your behalf.

1. Open your web browser and go to: https://go.dev/dl/
2. Download the Windows installer (it will be named something like go1.21.x.windows-amd64.msi).
3. Run the installer and follow the default prompts.
4. Click "Finish" when done.

To verify Go installed correctly, open a new Command Prompt and type:

    go version

You should see something like: go version go1.21.5 windows/amd64

[SCREENSHOT PLACEHOLDER: A Command Prompt window showing the successful output of "go version".]


STEP 5: INSTALL GIT AND CLONE THE JARVISJR REPOSITORY

Git is a tool for downloading and managing code from the internet.

5a. Install Git (if you do not have it already)

1. Go to: https://git-scm.com/download/win
2. Download the Windows installer and run it.
3. Accept all default settings during installation.

5b. Clone the Repository

Now you will download the JarvisJr project to your computer.

1. Open a Command Prompt.
2. Navigate to the folder where you want to install JarvisJr. For example, to put it on your Desktop:

    cd %USERPROFILE%\Desktop

3. Clone the repository by typing:

    git clone https://github.com/Smartchronon24/JarvisJrMCP.git

4. Once the download is complete, move into the project folder:

    cd JarvisJrMCP

Your JarvisJr project is now on your computer. The folder structure will look like this:

    JarvisJrMCP/
    |-- config/
    |   |-- settings.py          (controls the AI model and connected tools)
    |-- whatsapp-mcp/            (WhatsApp integration — already patched and included)
    |-- data/                    (local storage for memory, files, and browser data)
    |-- ollama_agent.py          (the main file that runs JarvisJr)
    |-- requirements.txt         (list of Python packages needed)
    |-- .env.example             (template for your secret credentials)
    |-- README.md


STEP 6: SET UP THE PYTHON ENVIRONMENT FOR JARVISJR

A virtual environment keeps JarvisJr's Python packages separate from the rest of your computer, preventing conflicts.

All of the following commands should be run from inside the JarvisJrMCP folder.

1. Create a virtual environment:

    python -m venv JarvisVenv

2. Activate the virtual environment. You will need to do this every time you open a new terminal to use JarvisJr:

    JarvisVenv\Scripts\activate

   After running this, you will see "(JarvisVenv)" appear at the beginning of your terminal prompt. This tells you the environment is active.

3. Install the required Python packages:

    pip install -r requirements.txt

   Wait for all packages to finish installing. This may take a minute or two.

[SCREENSHOT PLACEHOLDER: A terminal window showing the "(JarvisVenv)" prefix and the successful completion of "pip install -r requirements.txt".]


STEP 7: CONFIGURE YOUR SETTINGS

7a. Create Your Environment File

JarvisJr uses a file called ".env" to store private credentials. You must create this file from the provided template.

In your terminal, from inside the JarvisJrMCP folder, run:

    copy .env.example .env

Now open the newly created .env file in any text editor (Notepad is fine) and fill in your details. The file contains comments explaining each field.

7b. Configure the AI Model

Open the file config/settings.py in a text editor. Look for the line that says:

    OLLAMA_MODEL = "gpt-oss:120b-cloud"

If you downloaded a different model in Step 3, change this value to match the model name you pulled. For example:

    OLLAMA_MODEL = "llama3:8b"

Save and close the file.


STEP 8: SET UP WHATSAPP

The WhatsApp integration is the most powerful feature of JarvisJr. It requires a few extra steps because WhatsApp uses an end-to-end encrypted protocol that requires pairing with your phone.

There are two parts to the WhatsApp setup:
  A. Set up the Python MCP server (the part that JarvisJr talks to)
  B. Build and run the Go bridge (the part that talks to WhatsApp)
  C. Scan the QR code to link your WhatsApp account

IMPORTANT NOTE ABOUT THE PATCH:
The WhatsApp MCP server is based on an open-source project that contained a bug causing a "maximum recursion depth exceeded" crash in several tools. This bug has been diagnosed and fixed. The fixed version is already included in the JarvisJrMCP repository you cloned in Step 5, so you do not need to make any manual code changes.


8a. Set Up the WhatsApp MCP Python Environment

The WhatsApp server has its own separate Python environment. Navigate into its folder:

    cd whatsapp-mcp\whatsapp-mcp-server

Create and activate a virtual environment for it:

    python -m venv .venv
    .venv\Scripts\activate

Install its dependencies using pip:

    pip install httpx requests cryptography "anyio<4.14" mcp

You should see "(. venv)" in your prompt when this is done. Now go back to the main project folder:

    cd ..\..

8b. Build and Start the WhatsApp Go Bridge

The Go bridge is a background process that maintains a live connection to WhatsApp's servers. It must be running whenever you want Jarvis to use WhatsApp features.

Open a new, separate terminal window (keep your first terminal open). In the new window, navigate to the bridge folder inside your project:

    cd %USERPROFILE%\Desktop\JarvisJrMCP\whatsapp-mcp\whatsapp-bridge

Start the bridge:

    go run .

The first time you run this, Go will download and compile all required packages automatically. This may take a few minutes. Please be patient — subsequent starts will be much faster.

Once the bridge is ready, you will see a message indicating it is running and waiting for a QR code scan.

[SCREENSHOT PLACEHOLDER: The terminal showing the Go bridge starting up and displaying a QR code URL or the QR code itself in the terminal.]


8c. Scan the QR Code to Link Your WhatsApp Account

The Go bridge will display a QR code in the terminal (it looks like a grid of black and white characters). You need to scan this with your phone to link your WhatsApp account, similar to how WhatsApp Web works.

Step-by-step QR code scanning:

1. On your Android or iPhone, open WhatsApp.
2. Tap the three dots menu (Android) or go to Settings (iPhone).
3. Select "Linked Devices".
4. Tap "Link a Device".
5. Your phone camera will open. Point it at the QR code displayed in the terminal on your computer screen.
6. Hold steady until the code is recognised. WhatsApp will show "Linked" or similar confirmation.

If the QR code is hard to read in the terminal, the bridge may also print a URL in this format:
    https://quickchart.io/qr?text=...
You can copy and paste this URL into your browser to see a clearer, larger version of the QR code to scan.

Once the QR code is successfully scanned, the bridge terminal will show a confirmation message such as "Connection opened" or "Connected as [Your Name]". Your session is now saved — you will not need to scan the QR code again on this computer unless you log out.

[SCREENSHOT PLACEHOLDER: A phone screen showing the "Linked Devices" section in WhatsApp with the scanning camera open, pointed at the terminal QR code.]

[SCREENSHOT PLACEHOLDER: The Go bridge terminal showing a "Connection opened" or "Connected" success message after scanning.]


STEP 9: RUN JARVISJR

You are now ready to start JarvisJr. Make sure:
  - The Go WhatsApp bridge is still running in its own terminal window (from Step 8b).
  - You are in the JarvisJrMCP folder in your main terminal.
  - The JarvisVenv virtual environment is active (you see "(JarvisVenv)" in the prompt).

If the virtual environment is not active, run:

    JarvisVenv\Scripts\activate

Then start JarvisJr:

    python ollama_agent.py

JarvisJr will start and display a banner showing all the successfully connected MCP servers and tools:

    ============================================================
             JarvisJr, Personal AI Agent
    ============================================================

      Connected MCP Servers:
        memory      — OK
        filesystem  — OK
        playwright  — OK
        whatsapp    — OK

      Available Tools: [list of all tools]

    Jarvis>

You can now type any message and press Enter to interact with Jarvis.

[SCREENSHOT PLACEHOLDER: The full JarvisJr startup banner in the terminal showing all five MCP servers connected with checkmarks.]


---


5. FEATURES IN DETAIL


5.1 WHATSAPP INTEGRATION

WhatsApp is the centrepiece capability of JarvisJr in this Proof of Concept. Once set up, Jarvis acts as your intelligent assistant for reading and sending WhatsApp messages — all from a conversation in your terminal.

How It Works

When you ask Jarvis something like "Send a message to John saying I'll be late", Jarvis identifies the intent, uses the WhatsApp tool to search for a contact named John, finds his number, and sends the message on your behalf. It then confirms what it did.

The WhatsApp integration is powered by two components working together:
  1. The Python MCP Server (whatsapp-mcp-server) — handles the tool logic and exposes tools to Jarvis.
  2. The Go Bridge (whatsapp-bridge) — maintains a persistent, encrypted connection to WhatsApp using the same protocol as WhatsApp Web.

Your messages and contact data are never sent to any cloud service. Everything stays between your computer and WhatsApp's servers directly.

Available WhatsApp Tools

Jarvis has access to the following WhatsApp capabilities:

- Search Contacts: Find a contact by name or phone number.
    Example: "Find me John's WhatsApp contact"

- List Chats: Show your recent conversations.
    Example: "Show me my last 10 WhatsApp chats"

- Read Messages: Retrieve messages from a specific chat.
    Example: "What did Priya say to me today?"

- Send Messages: Send a text message to any contact or group.
    Example: "Send a message to Mum saying I'll call her tonight"

- Reply to Messages: Reply to a specific message in a conversation.
    Example: "Reply to John's last message saying sounds good"

- React to Messages: Add an emoji reaction to a message.
    Example: "React to that message with a thumbs up"

- Mark as Read: Mark messages as read across all your linked devices.
    Example: "Mark those messages as read"

[SCREENSHOT PLACEHOLDER: A terminal conversation where the user asks Jarvis to send a WhatsApp message, showing the tool call output and the confirmation response from Jarvis.]

[SCREENSHOT PLACEHOLDER: A terminal conversation where Jarvis lists recent WhatsApp chats in response to a user request.]

About the Bug Fix

The original open-source WhatsApp MCP server contained a programming error in its date-parsing function. Specifically, the function safe_parse_date was calling itself instead of Python's built-in date parser, causing an infinite loop that crashed the tool. This affected the following tools: list chats, get chat, get direct chat by contact, and get contact chats.

This was identified, diagnosed, and patched with a two-line correction. The fix is already applied in the version of the software included in this repository. You do not need to take any action.

Technical detail of the fix, for reference:
  Before: return safe_parse_date(d_str)     — (recursive, caused the crash)
  After:  return datetime.fromisoformat(d_str) — (correct, uses Python's built-in parser)

Important Considerations

- First-Time Setup: WhatsApp only sends your full chat and contact history to a newly linked device once, immediately after you scan the QR code. If you skip re-scanning or use an existing session, some older contacts may not appear immediately in searches.
- Privacy: JarvisJr can only access the WhatsApp account linked to the QR code you scanned. It cannot access any other account.
- Group Chats: JarvisJr fully supports group chats. You can read group messages and send messages to groups.


5.2 MEMORY — JARVIS REMEMBERS YOU

JarvisJr has a persistent memory system. You can tell Jarvis things about yourself, your preferences, or anything you want it to remember, and it will recall those details in future conversations — even after you close and reopen the application.

How It Works

Memory is stored as a structured knowledge graph in a local file on your computer: data/MemoryMCP/memory.jsonl. This file stores entities (people, places, things), observations (facts about those entities), and relationships between them.

Examples of What Jarvis Can Remember:
  - "Remember that my sister's name is Priya and her phone number is +91 98765 43210"
  - "My favourite restaurant is The Grand Palace on MG Road"
  - "I have a meeting every Tuesday at 10am"

In a future session, you can ask:
  - "What is my sister's phone number?"
  - "Where is my favourite restaurant?"

Jarvis will search its memory graph and respond with the correct information.

Privacy Note: All memories are stored only on your local machine. Nothing is sent to any external service.


5.4 WEB BROWSING WITH PLAYWRIGHT

JarvisJr can control a web browser on your behalf using a technology called Playwright. When you ask Jarvis to visit a website, it opens a real Chromium browser window on your computer, navigates to the page, reads the content, and can even interact with elements like buttons and forms.

Example Interactions:
  - "Open Google and search for the weather in Chennai"
  - "Go to https://example.com and tell me what is on the page"
  - "Click the Login button on the current page"

The browser opens visually so you can watch what Jarvis is doing in real time. Browser session data and screenshots are stored locally in data/PlaywrightMCP/.

Note: Jarvis uses structured page snapshots rather than raw screenshots when possible, which keeps the interaction accurate and efficient.


5.5 FILE SYSTEM ACCESS

JarvisJr can read from and write to files on your computer, but only within a designated safe folder: data/FilesystemMCP/. This is a deliberate safety measure — Jarvis cannot access files outside this folder, protecting your personal documents and system files.

Example Interactions:
  - "Create a file called notes.txt with the text 'Buy milk tomorrow'"
  - "Read the contents of the file report.txt"
  - "List all files in the folder"

Any files you want Jarvis to read must be placed in the data/FilesystemMCP/ folder first. Any files Jarvis creates will also appear there.


---


6. ARCHITECTURE OVERVIEW

JarvisJr follows a layered architecture:

![JarvisJr Architecture Diagram](C:\Users\navan\.gemini\antigravity\brain\e782e877-65c9-4e7b-b149-db0b3d583ed0\architecture_overview_1787129637190.jpg)

The diagram above shows how all components connect. At the top, the user interacts with the JarvisJr Command-Line Interface. JarvisJr Core (written in Python) sends messages to the Ollama model server to decide what to do next. When a tool is needed, it is dispatched to one of the MCP servers — Memory, Filesystem, Playwright, or WhatsApp. The WhatsApp MCP server is unique in that it also requires a companion Go bridge process that maintains the live connection to WhatsApp Web. Each server that handles data writes to its own isolated local folder. External services (WhatsApp Web and websites) are only contacted when the relevant tool is invoked.

Each MCP server is a separate, isolated process launched by JarvisJr at startup. They communicate with the core agent through a standardised protocol (MCP), which means new tools and capabilities can be added in the future without changing the core agent.


---


7. KNOWN LIMITATIONS AND DISCLAIMERS

The following are current limitations of this Proof of Concept. Many of these are planned to be addressed in future versions.

1. Windows Only: This version of JarvisJr has been built and tested exclusively on Windows. macOS and Linux support is planned for a future release.

2. WhatsApp QR Code Re-Scan: If you reinstall JarvisJr on a new machine or delete the session files, you will need to scan the WhatsApp QR code again. This is a WhatsApp security requirement.

5. Ollama Must Be Running: Ollama must be running in the background for JarvisJr to function. It starts automatically with Windows after installation, but if you ever see connection errors, check that the Ollama icon is present in your system tray.

6. Go Bridge Must Stay Running: The WhatsApp Go bridge must remain running in its own terminal window for the duration of your JarvisJr session. Closing that window will disconnect WhatsApp.

7. Model Token Limits: Very long conversations may eventually exceed the AI model's context window, causing it to lose track of earlier parts of the conversation. Starting a fresh session resolves this.

6. Internet Required for WhatsApp: WhatsApp features require an active internet connection. Memory, Filesystem, and (largely) Playwright can work offline.

This software is provided as a Proof of Concept for demonstration and evaluation purposes. It is not intended for production use without further hardening, testing, and review.


---


8. CREDITS

JarvisJr was designed and developed as a personal project integrating several open-source components:

- Ollama (https://ollama.com) — for running large language models locally.
- Model Context Protocol / MCP SDK (https://modelcontextprotocol.io) — the framework that connects Jarvis to its tools.
- WhatsApp MCP Server (https://github.com/verygoodplugins/whatsapp-mcp) — by Very Good Plugins, originally created by Luke Harries. Patched and bundled with permission under the MIT License.
- @modelcontextprotocol/server-memory — official MCP memory server.
- @modelcontextprotocol/server-filesystem — official MCP filesystem server.
- @playwright/mcp — Microsoft's official Playwright MCP server.


---

End of Document

JarvisJr, Personal AI Agent — Version 1.0 — Proof of Concept
