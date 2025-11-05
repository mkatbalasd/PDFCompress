# Project Plan: Web-Based PDF Compression Tool

**Objective:** Develop a secure and efficient web application that allows users to upload a PDF file, select a compression level, and download the compressed version.

**Core Agent Persona:** Expert Full-Stack Developer (Python/Flask + JavaScript).

---

### **Technology Stack**

*   **Backend:** Python 3, Flask
*   **Compression:** Ghostscript (CLI tool)
*   **Frontend:** HTML5, CSS3, JavaScript (ES6+, Fetch API)
*   **Project Structure:**
    ```
    /pdf-compressor
    |-- app.py             # Main Flask application
    |-- templates/
    |   |-- index.html     # Frontend HTML page
    |-- static/
    |   |-- style.css      # CSS for styling (optional but good practice)
    |   |-- script.js      # Client-side JavaScript logic
    |-- uploads/           # Temporary directory for uploaded files (must be created)
    |-- compressed/        # Temporary directory for compressed files (must be created)
    |-- requirements.txt   # Python dependencies (e.g., Flask)
    |-- README.md          # Project setup and usage instructions
    ```

---

### **Phase 1: Backend Implementation (`app.py`)**

1.  **Initialize Flask App:**
    *   Import necessary libraries: `Flask`, `request`, `send_from_directory`, `subprocess`, `os`, `uuid`.
    *   Configure temporary folders for uploads and compressed files. Ensure these folders exist.

2.  **Create `/compress` Endpoint:**
    *   Method: `POST`.
    *   Check for file presence in the request (`'file' not in request.files`).
    *   Get the uploaded file and the `compression_level` from `request.form`.
    *   Generate secure, unique filenames for the input and output files using `uuid.uuid4()`.
    *   Save the uploaded file to the `uploads/` directory.

3.  **Implement Compression Logic:**
    *   Create a dictionary to map `compression_level` strings (`low`, `medium`, `high`) to Ghostscript's `-dPDFSETTINGS` values (`/printer`, `/ebook`, `/screen`).
    *   Construct the full Ghostscript command as a list of arguments for `subprocess.run()`.
    *   **Example command:** `['gs', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4', '-dPDFSETTINGS=/ebook', '-dNOPAUSE', '-dBATCH', '-sOutputFile=path/to/output.pdf', 'path/to/input.pdf']`
    *   Execute the command using `subprocess.run()`, ensuring to check for errors (`check=True`).

4.  **Implement File Response & Cleanup:**
    *   Use a `try...finally` block.
    *   **In `try`:** After `subprocess.run()` succeeds, use `send_from_directory()` to return the compressed file.
    *   **In `finally`:** **This is critical.** Delete both the original uploaded file and the generated compressed file from the temporary directories using `os.remove()`. This ensures cleanup even if an error occurs during the response phase.

5.  **Create Root Route (`/`):**
    *   Method: `GET`.
    *   Render the `index.html` template.

---

### **Phase 2: Frontend Implementation**

1.  **HTML Structure (`templates/index.html`):**
    *   Create a `<form>` with `id="upload-form"`.
    *   Inside the form:
        *   `<input type="file" id="pdf-file" name="file" accept=".pdf" required>`
        *   `<select id="compression-level" name="compression_level">` with options for each level.
        *   `<button type="submit">Compress PDF</button>`
    *   Add a status `div` (e.g., `<div id="status"></div>`) to provide feedback to the user.

2.  **JavaScript Logic (`static/script.js`):**
    *   Get references to the form, file input, and status elements.
    *   Add a `submit` event listener to the form.
    *   Inside the listener function:
        *   Call `event.preventDefault()`.
        *   Update status: "Uploading and compressing... please wait."
        *   Create `FormData` and append the file and compression level.
        *   Use `fetch('/compress', { method: 'POST', body: formData })`.
        *   **Handle Success:**
            *   Check if `response.ok` is true.
            *   Get the file data as a blob: `response.blob()`.
            *   Create a download link:
                *   `const url = URL.createObjectURL(blob);`
                *   `const a = document.createElement('a');`
                *   Set `a.href`, `a.download`, and `a.style.display = 'none'`.
                *   `document.body.appendChild(a);`
                *   `a.click();`
                *   Clean up: `window.URL.revokeObjectURL(url);` and `a.remove()`.
            *   Update status: "Download started successfully!"
        *   **Handle Failure:**
            *   Update status with an error message: "An error occurred during compression."

---

### **Phase 3: Finalization**

1.  **Create `requirements.txt`:**
    ```
    Flask
    ```
2.  **Create `README.md`:**
    *   Provide a brief description of the project.
    *   List prerequisites: `Python 3`, `pip`, and **`Ghostscript`**. Emphasize that Ghostscript must be installed and accessible in the system's PATH.
    *   Provide setup and run instructions:
        1.  `git clone ...`
        2.  `pip install -r requirements.txt`
        3.  `mkdir uploads compressed`
        4.  `flask run`