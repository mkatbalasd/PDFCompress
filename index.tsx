const uploadForm = document.getElementById('upload-form') as HTMLFormElement;
const pdfFileInput = document.getElementById('pdf-file') as HTMLInputElement;
const compressionLevelSelect = document.getElementById('compression-level') as HTMLSelectElement;
const statusDiv = document.getElementById('status') as HTMLDivElement;
const submitButton = document.getElementById('submit-button') as HTMLButtonElement;
const submitButtonText = submitButton.querySelector('span');

const showStatus = (message: string, type: 'info' | 'success' | 'error') => {
    statusDiv.textContent = message;
    statusDiv.className = `status-${type}`;
};

const setLoadingState = (isLoading: boolean) => {
    if (isLoading) {
        submitButton.disabled = true;
        if(submitButtonText) submitButtonText.textContent = 'Compressing...';
        const loader = document.createElement('div');
        loader.className = 'loader';
        submitButton.prepend(loader);
    } else {
        submitButton.disabled = false;
        if(submitButtonText) submitButtonText.textContent = 'Compress PDF';
        const loader = submitButton.querySelector('.loader');
        if (loader) {
            loader.remove();
        }
    }
};

uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!pdfFileInput.files || pdfFileInput.files.length === 0) {
        showStatus('Please select a PDF file to compress.', 'error');
        return;
    }

    const file = pdfFileInput.files[0];
    const compressionLevel = compressionLevelSelect.value;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('compression_level', compressionLevel);

    setLoadingState(true);
    showStatus('Uploading and compressing... This may take a moment.', 'info');

    try {
        // NOTE: This fetch call assumes a backend server is running at `/compress`
        // as described in the project plan. This frontend-only implementation
        // cannot perform the compression itself.
        const response = await fetch('/compress', {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Compression failed: ${response.status} ${response.statusText}. ${errorText}`);
        }

        const blob = await response.blob();
        
        // Create a temporary link to trigger the download
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const originalName = file.name.replace(/\.pdf$/i, '');
        a.download = `${originalName}_compressed.pdf`;
        document.body.appendChild(a);
        a.click();
        
        // Clean up the temporary link
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showStatus('Compression successful! Your download has started.', 'success');
        uploadForm.reset();

    } catch (error) {
        console.error('An error occurred:', error);
        showStatus('An error occurred during compression. Please ensure the backend server is running and check the console for details.', 'error');
    } finally {
        setLoadingState(false);
    }
});
