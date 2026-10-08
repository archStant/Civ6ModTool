# Civ 6 Mod Generator

A desktop tool for making Civilization VI mods without writing SQL or XML. It generates:

- **Leaders**: alternate leaders for existing civilizations, or new leaders with their own ability, agenda and AI personality.
- **Civilizations**: new civilizations with an ability, city and citizen names, start bias, Civilopedia text, art style and music.
- **Uniques**: unique units, buildings, districts and improvements, either copied from the game's items and changed, or made from scratch, with their own stats, yields, effects, placement rules and 3D models.

The output is a complete mod folder that the game loads like any other mod. It can be published on the Steam Workshop with the SDK's uploader.

### What it does not do
Any sort of modding beyond the above mentioned, such as new ressources, great people, yields, governors, beliefs, etc. etc. etc. will still require you to open ModBuddy and write the code yourself.

## Acknowledgements
Many many thanks to [Maconnolly](https://forums.civfanatics.com/members/maconnolly.319458/) for his very thorough mod template and instructions. This was the Rosetta stone for getting into Civ 6 modding for me and many others.

## Requirements

- Windows, with Civilization VI installed through Steam. Rise and Fall and Gathering Storm are supported but not required. Make sure that your game has been run, and a actual game has been started at least once.
- **The Civilization VI SDK.** In Steam, open *Library*, switch the filter to *Tools* and install **Sid Meier's Civilization VI Development Tools**. The generator uses two parts of it:
  - **Asset cooker** (`AssetModTools\Cooker`): turns your images into the texture packages the game loads. Without it, custom icons, portraits, backgrounds and historic moment pictures are skipped, and the mod falls back to the game's own art.
  - **Workshop uploader** (`ModUploader`): needed to publish the mod on the Steam Workshop.

  You do not need the separate *Development Assets* package. The generator finds the SDK in your Steam libraries automatically, or asks for its location.
- Running from source: Python 3 (developed with 3.14), plus Pillow (`pip install -r requirements.txt`). Pillow converts your images; without it, custom art is skipped as above.

## Getting started

1. Start the game once with the expansions you use enabled (preferably Gathering Storm), then quit. This writes the game's data cache, which the generator reads.
2. Run the generator: `Civ6ModGenerator.exe`, or `python main.py` from source.
3. Click **Load game data...** in the toolbar. Until you do, the status bar shows a red warning and the editors only offer a small built-in list.
4. Add civilizations and leaders, set a mod name and a type prefix (e.g. your initials, so your types do not clash with other mods), then click **Generate mod** (F5).
5. The mod is written to the output folder, by default the game's `Mods` folder (`Documents\My Games\Sid Meier's Civilization VI\Mods`). Enable it under *Additional Content* in the game.

If the game fails to load a mod, check `Database.log` and `Modding.log` in `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Logs`.

## Publishing on the Steam Workshop

**Publish to Workshop...** checks the generated mod against the uploader's rules and prepares the Workshop page: title, description, preview image and change notes. It then opens the SDK's uploader, which has no command line, and lists what to enter, with Copy buttons.

A mod keeps its id from build to build, so uploading again updates the same Workshop item. Raise the version for each update.

## Projects

Work is saved as `.civmod` project files (plain JSON). Images are referenced by their path on disk, not copied into the project.

**Export...** and **Import...** move leaders and civilizations, with their images, between projects or computers.

## Building the executable

```
pip install -r requirements.txt
powershell -File build.ps1
```

This uses Nuitka to build `Civ6ModGenerator.exe`, a single file that bundles the `assets` folder.

## Tests

```
python -m unittest discover -s tests -t .
```

Most tests generate mods and run their SQL against copies of the game's own databases. They need the game installed and its cache written (see *Getting started*). Tests that check Gathering Storm content are skipped when the cache is from another ruleset.

## Limitations

- **3D models** are assembled from the game's existing models and meshes. New models cannot be imported.
- **Leaders** have no animated 3D scene. The diplomacy screen shows a 2D image made from the loading portrait, or another leader's scene.
- **Effects** are built from a library of the game's modifier types. Some only exist with the expansions.
- **DLC items:** a mod that copies an item from a DLC needs that DLC to be enabled.
