venv\Scripts\activate.ps1
if ($?) {
    Write-Host "Virtual environment activated successfully."
} else {
    Write-Host "Failed to activate virtual environment."
    exit 1
}
nuitka --standalone `
    --onefile `
    --enable-plugin=tk-inter `
    --include-data-dir=assets=assets `
    --windows-console-mode=disable `
    --windows-icon-from-ico=app.ico `
    --product-name="Civ6ModGenerator" `
    --file-version=1.0 `
    --product-version=1.0 `
    --file-description="Civ6ModGenerator" `
    --output-dir=dist `
    --output-filename=Civ6ModGenerator.exe main.py