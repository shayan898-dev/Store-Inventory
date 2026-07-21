# Inventory Manager

This repository contains the source code and build artifacts for a Python-based Inventory Manager application. It features core modules for handling database operations and a dedicated barcode scanner script to process scanned item inputs, such as those integrated from a mobile phone. Additionally, the project is configured for standalone distribution, utilizing a PyInstaller `.spec` file and automated build scripts to compile the application into an executable format.

## How to Use After Downloading

Once you download the ZIP file, follow these steps to run or modify the application:

### 1. Extract the Archive
Unzip the downloaded file into a dedicated folder on your computer.

### 2. Run the Source Code
*   Ensure you have Python installed. Note: the cached files were generated with Python 3.14.
*   Navigate to the extracted directory in your terminal.
*   Execute the primary application script by running:
    ```bash
    python main.py
    ```

### 3. Compile the Application
*   To generate a fresh, standalone executable, run the included build utility using:
    ```bash
    python build_app.py
    ```
*   Alternatively, you can manually trigger the build process by running:
    ```bash
    pyinstaller InventoryManager.spec
    ```

### 4. Review Documentation
Open the `FEATURES.md` file to read through the documented functionalities and any specific setup instructions for the system.
