const form = document.getElementById("compress-form");
const statusElement = document.getElementById("status");
const fileInput = document.getElementById("pdf-file");
const submitButton = form?.querySelector("button[type='submit']");

const setStatus = (message, variant = "info") => {
  statusElement.textContent = message;
  statusElement.dataset.variant = variant;
};

const buildDownloadName = (file) => {
  if (!file?.name) {
    return "compressed.pdf";
  }
  const baseName = file.name.replace(/\.[^.]+$/, "");
  return `${baseName || "document"}-compressed.pdf`;
};

const handleError = async (response) => {
  const defaultMessage = "An error occurred while compressing your PDF.";
  try {
    const data = await response.json();
    return data?.message || defaultMessage;
  } catch (error) {
    return defaultMessage;
  }
};

if (form && fileInput && statusElement && submitButton) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (fileInput.files.length === 0) {
      setStatus("Please choose a PDF file first.", "error");
      return;
    }

    submitButton.disabled = true;
    setStatus("Uploading and compressing…", "info");

    const formData = new FormData(form);

    try {
      const response = await fetch("/compress", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const message = await handleError(response);
        throw new Error(message);
      }

      const blob = await response.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = buildDownloadName(fileInput.files[0]);
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(downloadUrl);
      setStatus("Compression complete! Your download should begin shortly.", "success");
      form.reset();
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      submitButton.disabled = false;
    }
  });
}
