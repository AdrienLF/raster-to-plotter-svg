# Portable Project Archives

## Goal

Let a user save the complete current PlotterForge project as one portable
file, then open that file later as a new project and continue editing it.
Existing automatic local persistence remains unchanged.

## User Experience

The Project menu gains two actions:

- **Save project file…** downloads the current project as a
  `<project-name>.plotter-project` file.
- **Open project file…** opens a file picker restricted to project archives,
  imports the selected archive as a new local project, and selects it.

Opening an archive never replaces the current project. Each import receives a
fresh internal project ID, so importing the same archive more than once creates
independent projects. The imported project keeps its saved display name; the
existing project list and unique internal IDs disambiguate copies.

Successful import uses the normal project-switch refresh path so the image,
composition, selected layer, generator and path-finding parameters, regions,
painted fields, pens, versions, and editor controls all reflect the imported
project. Errors appear in the existing status/log area.

## Archive Format

The `.plotter-project` file is a ZIP archive containing the current project
directory. Its root contains:

- `archive.json`, with `format_version: 1` and the exporting application name;
- `project.json`, using the existing project manifest schema.

Depending on project content it may also contain:

- the original source image;
- composition layer SVG files;
- region masks and previews;
- painted-field masks;
- saved-version thumbnails and composition snapshots.

Paths inside the manifest and archive are relative to the project root. The
archive contains no machine-specific absolute paths. Archive metadata is kept
separate from the project manifest so normal project loading remains the single
source of truth. Import accepts archive format version 1 only.

Before export, the backend flushes the current manifest and composition layer
files. The archive is assembled in memory or in a temporary file and streamed
as a download; export does not mutate the project.

## Backend Interfaces

### Export

`GET /api/projects/<project-id>/archive` exports the requested project. The UI
uses the current project ID. The endpoint returns the archive with an attachment
filename derived from the sanitized project name.

Export returns `404` for an unknown project and `409` if a project transition
or active operation makes a consistent snapshot unavailable.

### Import

`POST /api/projects/import` accepts one multipart archive. Import proceeds in a
temporary directory:

1. Validate the upload and archive limits.
2. Safely extract entries while rejecting absolute paths, parent traversal,
   symlinks, and other non-regular entries.
3. Require exactly one root `archive.json` and `project.json`, accept archive
   format version 1, and validate the project manifest structure.
4. Validate every manifest-referenced asset path and require referenced files
   to exist inside the extracted root.
5. Assign a fresh project ID in both the destination directory and manifest.
6. Stage it in a non-discoverable directory on the Projects filesystem, then
   rename that directory atomically to the fresh project ID.
7. Open it through the existing project-switch path and return the same current
   project and project-list payload used by New/Open Project.

If any step fails, the temporary files are removed, the current project remains
selected, and no partial project appears in the library.

## Safety and Limits

Import allows at most 512 MiB uploaded, 10,000 entries, 256 MiB uncompressed per
entry, and 1 GiB uncompressed in total. ZIP metadata sizes are checked before
extraction, while streamed extraction also enforces actual byte limits to guard
against misleading metadata and ZIP bombs.

Archive entries must be relative, normalized paths beneath the extraction root.
Duplicate normalized paths, encrypted entries, symlinks, devices, and nested
archive roots are rejected. Only files that belong to the project are exported.

Malformed JSON, unsupported manifest values, missing assets, and unreadable
archives produce a controlled `400` response. Limit violations produce `413`.
Server-side I/O failures produce `500` without exposing filesystem paths.

## Frontend Flow

The menu owns a hidden project-file input separate from the existing image/SVG
input. Save calls a download helper that preserves the server-provided filename.
Open uploads the selected file, clears the input afterward so the same file can
be reopened, then passes the successful response through the existing
`switchProject` flow. While either request is active, duplicate actions are
disabled and the status area reports Saving or Opening.

## Testing

Backend tests cover:

- a complete project round-trip including image, layers, masks, painted fields,
  versions, and their binary assets;
- fresh IDs and independent directories across repeated imports;
- export of both the current and another known project;
- rejection of traversal, absolute paths, symlinks, duplicate paths, encrypted
  entries, oversized archives, corrupt ZIPs, invalid manifests, and missing
  referenced assets;
- atomic cleanup and preservation of the current project after failed import.

Browser tests cover:

- Save project file produces a non-empty `.plotter-project` download;
- Open project file creates and selects a new project;
- restored editable state matches the exported project;
- importing the same archive twice creates independent projects;
- an invalid archive reports an error without switching projects.

## Out of Scope

- Replacing an existing project during import.
- Continuous synchronization to a user-selected filesystem location.
- Cloud storage, sharing, or collaboration.
- Importing arbitrary folders or hand-authored JSON.
- Migrating archives from future incompatible manifest versions.
