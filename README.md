# LiveScribe

## Description

LiveScribe: Real-time speech transcription and translation that bridges language gaps. Get instant, accurate captions in multiple languages via a web interface. Powered by Azure, Google Cloud, and DeepL. Perfect for meetings, live streams, and more. Open source and ready for your contributions!

## Demo
<div style="padding:56.25% 0 0 0;position:relative;">
    <iframe src="https://player.vimeo.com/video/1057743327?badge=0&autopause=1&player_id=0&app_id=58479" frameborder="0" allow="fullscreen; picture-in-picture; clipboard-write; encrypted-media" style="position:absolute;top:0;left:0;width:100%;height:100%;" title="LiveScribe Demo"></iframe>
</div>
<p>Click the video above to see a demonstration of LiveScribe.</p>

## Table of Contents

*   [Features](#features)
*   [Technologies Used](#technologies-used)
*   [Prerequisites](#prerequisites)
*   [Installation](#installation)
*   [Configuration](#configuration)
*   [Usage](#usage)
*   [Architecture](#architecture)
*   [API Endpoints](#api-endpoints)
*   [Customization](#customization)
    *   [Custom Phrases](#custom-phrases)
*   [Error Handling and Fallback](#error-handling-and-fallback)
*   [Caching](#caching)

## Features

*   **Real-time Speech Transcription:**  Converts spoken audio into text with low latency.
*   **Multi-language Translation:**  Translates transcribed text into multiple languages using various translation services.
*   **Web-based Interface:**  Displays transcriptions and translations in a user-friendly web interface.
*   **Multiple Service Providers:** Supports Azure Cognitive Services, Google Cloud Translation, and DeepL Translator.
*   **Fallback Mechanism:**  Automatically switches to alternative translation services if the primary service fails.
*   **Caching:**  Implements a translation cache to improve performance and reduce API calls.
*   **Customizable Vocabulary:**  Allows adding custom phrases and keywords to improve recognition accuracy.
*   **Open Source:**  The project is open source, encouraging community contributions.
*   **WebSocket Communication:** Uses Socket.IO for real-time, bidirectional communication between the server and client.
*  **Text Formatting:** Formats recognized text by splitting into sentences and paragraphs, to avoid text too long.

## Technologies Used

*   **Python 3.7+** (It's a good practice to specify a minimum Python version)
*   **Flask:**  Web framework for creating the application.
*   **Flask-SocketIO:**  Enables real-time communication with the client.
*   **Azure Cognitive Services Speech SDK:**  For speech-to-text and translation (optional, if using Azure).
*   **Google Cloud Translation API:**  For translation (optional, if using Google Cloud).
*   **DeepL Python Library:**  For translation (optional, if using DeepL).
*   **python-dotenv:**  For managing environment variables.
*   **cachetools:** For caching translations.
*   **JavaScript (ES6+):**  For the frontend client.
*   **Socket.IO Client:**  For real-time communication with the server.
*   **HTML/CSS:**  For the user interface.

## Prerequisites

1.  **Python 3.7+:**  Ensure Python 3.7 or higher is installed on your system.
2.  **pip:**  The Python package installer.
3.  **Cloud Service Accounts:**
    *   **Azure:**  An Azure subscription with access to Cognitive Services (Speech and Translator).  You'll need a Speech key and region, and a Translator key and region.
    *   **Google Cloud:**  A Google Cloud Platform project with the Cloud Translation API enabled.  You'll need a service account key file (JSON).
    *   **DeepL:**  A DeepL API key.

## Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/s-chyi/LiveScribe.git
    cd LiveScribe
    ```

2.  **Create a virtual environment (recommended):**

    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Linux/macOS
    venv\Scripts\activate  # On Windows
    ```

3.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4. **Create a `.env` file:**
    Create a file named `.env` in the root directory of your project. Add the following environment variables, replacing the placeholders with your actual credentials:

    ```
    SPEECH_KEY=<your_azure_speech_key>
    SPEECH_REGION=<your_azure_speech_region>
    AZURE_TRANSLATOR_KEY=<your_azure_translator_key>
    AZURE_TRANSLATOR_REGION=<your_azure_translator_region>
    DEEPL_KEY=<your_deepl_api_key>
    GOOGLE_PROJECT=<your_google_project>
    ```
    
5. **Google Cloud Credentials**
   Place your Google Cloud service account key JSON file inside the `credentials/` directory. *Important Security Note:*  Do *not* commit this JSON file to your Git repository.

## Configuration

*   **`RECOGNIZER`:**  Set to `"Azure"` (default) in `app.py`.
*   **`TRANSLATOR`:**  Set to `"Azure"`, `"DeepL"`, or `"Google"` in `app.py`.  Select your preferred translation provider.
*   **`FILE_NAME`:**  Set to `None` (default) to use the default microphone.  Alternatively, provide the path to a WAV audio file for transcription and translation.
*   **`PROJECT_ID` and `PARENT`:** (Google Cloud) Set these if using Google Cloud Translation. `PROJECT_ID` is your Google Cloud project ID.  `PARENT` is derived from it.

## Usage

1.  **Start the application:**

    ```bash
    python app.py
    ```

2.  **Open your web browser and go to:**

    ```
    http://localhost:5015
    ```
    (or the address/port displayed in your console).

3.  The application will start listening for audio (from your microphone or the specified file) and display the real-time transcription and translation.

## Architecture

The application follows a client-server architecture:

*   **Client (Frontend):**  The `index.html` file, along with `static/css/styles.css` and `static/js/client.js`, provides the user interface.  It uses JavaScript and Socket.IO to communicate with the server in real-time.
*   **Server (Backend):**  The `app.py` file uses Flask and Flask-SocketIO to handle client connections, manage the speech recognition and translation processes, and send updates to the client.
*   **ContinuousTranslation Class:**  This class is the core of the backend.  It handles:
    *   Initializing and managing the speech recognizer (Azure or Azure Docker).
    *   Connecting to the recognizer's events (`recognizing`, `recognized`, `session_started`, `session_stopped`, `canceled

*   Connecting to the recognizer's events (`recognizing`, `recognized`, `session_started`, `session_stopped`, `canceled`).
    *   Calling the translation functions.
    *   Managing the translation cache.
    *   Handling fallback logic between different translation providers.
    *   Formatting the output text for display.
    *   Writing logs and transcripts to files.
*   **TranslationManager Class:** This class handles the translation requests, including caching and the fallback mechanism. It uses an `asyncio.Semaphore` to limit concurrent translation requests and a `TranslationCache` to store previous translations.
*   **TranslationCache Class:** A simple wrapper around `cachetools.TTLCache` to provide a time-to-live (TTL) cache for translations.

## API Endpoints

*   **`/` (GET):**  Serves the `index.html` page.
*   **Socket.IO Events:**
    *   `connect`:  Triggered when a client connects.  Logs the client's IP address.
    *   `disconnect`:  Triggered when a client disconnects.  Logs the disconnection.
    *   `update_text`:  (Server to Client) Sends updated text and language information to the client.
    *   `ping` and `pong`: Used for simple keep-alive.

## Customization

### Custom Phrases

The `custom_phrases` list in `app.py` allows you to add words or phrases that the speech recognizer might have difficulty with.  This improves recognition accuracy for domain-specific terms.  Add your custom phrases to this list as strings.

```python
custom_phrases = [
    "AI", "Machine Learning", "Nick"
]
```

## Error Handling and Fallback

The `TranslationManager` class implements a fallback mechanism.  If the selected `TRANSLATOR` fails repeatedly (more than `error_threshold` times), the system will attempt to use alternative translators in the order defined by `fallback_order`.  Error counts are tracked in `error_counts`. The `translate_with_fallback` method handles the actual fallback logic.

## Caching

The `TranslationCache` class uses `cachetools.TTLCache` to cache translation results. This reduces the number of calls to the translation APIs, improving performance and potentially reducing costs.  The cache size (`max_size`) and expiration time (`ttl`) can be configured in the `TranslationManager`'s constructor.
