# Portable Project Archives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add downloadable `.plotter-project` archives that preserve a complete editable project and can be imported later as a new local project.

**Architecture:** A focused `engine.project_archive` module owns archive assembly, validation, limits, safe extraction, and atomic installation. Flask routes translate its typed errors into HTTP responses, while the existing project-switch flow remains the only way the frontend hydrates imported state. The Svelte UI adds a dedicated project-file picker and download action without changing existing image/SVG import behavior.

**Tech Stack:** Python 3.13 standard library (`zipfile`, `tempfile`, `pathlib`, `json`, `stat`, `shutil`), Flask, Svelte 5/TypeScript, Playwright, unittest/pytest.

## Global Constraints

- The archive extension is `.plotter-project` and the wire format is ZIP.
- Root files are exactly one `archive.json` with `format_version: 1` and one `project.json` using the existing project schema.
- Import always creates a new project with a fresh 10-character hexadecimal ID; it never replaces the current project.
- Maximum upload is 512 MiB, maximum entries is 10,000, maximum uncompressed entry size is 256 MiB, and maximum total uncompressed size is 1 GiB.
- Reject absolute paths, `..`, backslashes, duplicate normalized paths, encryption, symlinks, devices, directories, unreferenced files, and missing referenced assets.
- Failed import leaves the current project and project list unchanged and removes all staging files.
- No new runtime dependencies.

---

## File Structure

- Create `engine/project_archive.py`: archive format constants, referenced-asset discovery, export, validation, bounded extraction, and atomic import.
- Modify `engine/project.py`: hide dot-prefixed staging directories from `list_projects()`.
- Modify `web/server.py`: project archive export/import routes and HTTP error translation.
- Modify `frontend/src/lib/state.svelte.ts`: one `projectFileBusy` UI state flag.
- Modify `frontend/src/lib/api.ts`: project archive download/upload flows.
- Modify `frontend/src/components/MenuBar.svelte`: Project menu actions and disabled states.
- Modify `frontend/src/App.svelte`: dedicated hidden project-file input.
- Create `tests/test_project_archive.py`: focused archive unit tests.
- Modify `tests/test_projects.py`: Flask route, switching, and atomicity tests.
- Modify `frontend/e2e/a-projects.spec.ts`: user-facing Save/Open journeys.
- Rebuild `web/static/app/`: checked-in production frontend assets.

---

### Task 1: Deterministic Complete Project Export

**Files:**
- Create: `engine/project_archive.py`
- Create: `tests/test_project_archive.py`

**Interfaces:**
- Consumes: `engine.project.Project`, including `save_composition_layers()`, `to_dict()`, and `dir`.
- Produces: `ARCHIVE_MIMETYPE: str`, `archive_filename(project: Project) -> str`, `build_project_archive(project: Project) -> io.BytesIO`, and `_referenced_asset_paths(manifest: dict) -> set[str]` for later import validation.

- [ ] **Step 1: Write the failing complete-export test**

```python
# tests/test_project_archive.py
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from engine import project as project_mod
from engine.project_archive import archive_filename, build_project_archive


SVG = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L10 10"/></svg>'


class ProjectArchiveTest(unittest.TestCase):
    def setUp(self):
        self.original_projects_dir = project_mod.PROJECTS_DIR
        self.tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self.tmp.name)
        self.project = project_mod.create_project('Archive / Demo')
        self.project.set_image(b'not-needed-for-decoding', 'source.bin')
        layer = self.project.composition.add_layer(SVG, 'Layer', 'svg', {'filename': 'layer.svg'})
        self.project.save_composition_layers()
        self.project.add_region('Region', Image.new('L', (4, 4), 255))
        self.project.add_field_mask('Paint', Image.new('L', (4, 4), 127))
        self.project.add_version(None, name='Snapshot', thumbnail=Image.new('RGB', (8, 8), 'white'))
        self.layer = layer

    def tearDown(self):
        project_mod.PROJECTS_DIR = self.original_projects_dir
        self.tmp.cleanup()

    def test_export_contains_manifest_and_every_referenced_asset(self):
        payload = build_project_archive(self.project)

        with zipfile.ZipFile(payload) as archive:
            names = set(archive.namelist())
            metadata = json.loads(archive.read('archive.json'))
            manifest = json.loads(archive.read('project.json'))

        self.assertEqual(metadata, {'application': 'PlotterForge', 'format_version': 1})
        self.assertEqual(manifest['id'], self.project.id)
        self.assertIn('source.bin', names)
        self.assertIn(self.layer.svg_path, names)
        self.assertIn(self.project.regions[0].mask_path, names)
        self.assertIn(self.project.field_masks[0]['path'], names)
        self.assertIn(self.project.versions[0].thumbnail, names)
        self.assertIn(self.project.versions[0].composition_snapshot, names)
        self.assertEqual(
            names,
            {
                'archive.json', 'project.json', 'source.bin', self.layer.svg_path,
                self.project.regions[0].mask_path, self.project.field_masks[0]['path'],
                self.project.versions[0].thumbnail,
                self.project.versions[0].composition_snapshot,
            },
        )

    def test_archive_filename_is_sanitized(self):
        self.assertEqual(archive_filename(self.project), 'Archive-Demo.plotter-project')
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `.venv/bin/python -m pytest tests/test_project_archive.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'engine.project_archive'`.

- [ ] **Step 3: Implement metadata, referenced assets, filename sanitizing, and export**

```python
# engine/project_archive.py
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from .project import Project

ARCHIVE_MIMETYPE = 'application/vnd.plotterforge.project+zip'
ARCHIVE_FORMAT_VERSION = 1


def _safe_relative_path(value: object) -> str:
    raw = str(value or '')
    if not raw or '\\' in raw:
        raise ValueError(f'Invalid project asset path: {raw!r}')
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or path.as_posix() != raw
        or any(part in {'', '.', '..'} for part in path.parts)
    ):
        raise ValueError(f'Invalid project asset path: {raw!r}')
    return path.as_posix()


def _referenced_asset_paths(manifest: dict) -> set[str]:
    candidates: list[object] = []
    if manifest.get('image_name'):
        candidates.append(manifest['image_name'])
    for layer in (manifest.get('composition') or {}).get('layers', []):
        if layer.get('svg_path'):
            candidates.append(layer['svg_path'])
    for region in manifest.get('regions', []):
        candidates.extend(path for path in (region.get('mask_path'), region.get('preview_path')) if path)
    for field_mask in manifest.get('field_masks', []):
        if field_mask.get('path'):
            candidates.append(field_mask['path'])
    for version in manifest.get('versions', []):
        candidates.extend(path for path in (version.get('thumbnail'), version.get('composition_snapshot')) if path)
    return {_safe_relative_path(path) for path in candidates}


def archive_filename(project: Project) -> str:
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', project.name).strip('._-') or 'project'
    return f'{stem}.plotter-project'


def build_project_archive(project: Project) -> io.BytesIO:
    project.save_composition_layers()
    manifest = project.to_dict()
    assets = _referenced_asset_paths(manifest)
    missing = sorted(
        path
        for path in assets
        if not (project.dir / path).is_file() or (project.dir / path).is_symlink()
    )
    if missing:
        raise ValueError(f'Missing project asset: {missing[0]}')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            'archive.json',
            json.dumps({'application': 'PlotterForge', 'format_version': ARCHIVE_FORMAT_VERSION}, indent=2),
        )
        archive.writestr('project.json', json.dumps(manifest, indent=2))
        for relative in sorted(assets):
            archive.write(project.dir / Path(relative), relative)
    output.seek(0)
    return output
```

- [ ] **Step 4: Run the focused tests**

Run: `.venv/bin/python -m pytest tests/test_project_archive.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the export unit**

```bash
git add engine/project_archive.py tests/test_project_archive.py
git commit -m "feat: export complete project archives"
```

---

### Task 2: Secure Bounded Atomic Archive Import

**Files:**
- Modify: `engine/project_archive.py`
- Modify: `engine/project.py:392-406`
- Modify: `tests/test_project_archive.py`

**Interfaces:**
- Consumes: Task 1 `_referenced_asset_paths()` and archive constants.
- Produces: `ProjectArchiveError(message: str, status_code: int = 400)`, `import_project_archive(stream: BinaryIO) -> Project`, and staging directories excluded by `list_projects()`.

- [ ] **Step 1: Add failing happy-path, fresh-ID, and cleanup tests**

```python
# append to tests/test_project_archive.py imports
import shutil
from engine.project_archive import ProjectArchiveError, import_project_archive

# append to ProjectArchiveTest
    def test_import_creates_independent_project_with_fresh_id(self):
        payload = build_project_archive(self.project)

        imported = import_project_archive(payload)

        self.assertNotEqual(imported.id, self.project.id)
        self.assertEqual(imported.name, self.project.name)
        self.assertEqual(imported.composition.layers[0].svg, SVG)
        self.assertTrue(imported.image_path.is_file())
        self.assertTrue((imported.dir / imported.regions[0].mask_path).is_file())
        self.assertTrue((imported.dir / imported.field_masks[0]['path']).is_file())
        self.assertTrue((imported.dir / imported.versions[0].thumbnail).is_file())

    def test_repeated_imports_receive_distinct_ids(self):
        data = build_project_archive(self.project).getvalue()
        first = import_project_archive(io.BytesIO(data))
        second = import_project_archive(io.BytesIO(data))
        self.assertNotEqual(first.id, second.id)
        self.assertTrue(first.dir.is_dir())
        self.assertTrue(second.dir.is_dir())

    def test_failed_import_removes_hidden_staging_directory(self):
        with self.assertRaises(ProjectArchiveError):
            import_project_archive(io.BytesIO(b'not a zip'))
        self.assertEqual(list(project_mod.PROJECTS_DIR.glob('.import-*')), [])
```

- [ ] **Step 2: Run the new tests and verify import is missing**

Run: `.venv/bin/python -m pytest tests/test_project_archive.py -q`

Expected: collection fails because `ProjectArchiveError` and `import_project_archive` are not defined.

- [ ] **Step 3: Implement bounded reading, ZIP-info validation, extraction, manifest checks, and atomic rename**

```python
# add imports in engine/project_archive.py
import shutil
import stat
import tempfile
import uuid
from typing import BinaryIO

from . import project as project_mod

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 10_000
MAX_ENTRY_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


class ProjectArchiveError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _read_upload(stream: BinaryIO):
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    total = 0
    while True:
        chunk = stream.read(COPY_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            spool.close()
            raise ProjectArchiveError('Project archive exceeds 512 MiB', 413)
        spool.write(chunk)
    spool.seek(0)
    return spool


def _entry_path(info: zipfile.ZipInfo) -> str:
    try:
        path = _safe_relative_path(info.filename)
    except ValueError as exc:
        raise ProjectArchiveError(str(exc)) from exc
    if info.is_dir():
        raise ProjectArchiveError(f'Directory entries are not allowed: {path}')
    if info.flag_bits & 0x1:
        raise ProjectArchiveError(f'Encrypted entries are not allowed: {path}')
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind not in {0, stat.S_IFREG}:
        raise ProjectArchiveError(f'Non-regular entry is not allowed: {path}')
    if info.file_size > MAX_ENTRY_BYTES:
        raise ProjectArchiveError(f'Archive entry exceeds 256 MiB: {path}', 413)
    return path


def _validated_infos(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ProjectArchiveError('Project archive has more than 10000 entries', 413)
    if sum(info.file_size for info in infos) > MAX_TOTAL_BYTES:
        raise ProjectArchiveError('Project archive expands beyond 1 GiB', 413)
    result: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    for info in infos:
        path = _entry_path(info)
        key = path.casefold()
        if key in folded:
            raise ProjectArchiveError(f'Duplicate archive path: {path}')
        folded.add(key)
        result[path] = info
    return result


def _read_json(archive: zipfile.ZipFile, info: zipfile.ZipInfo, label: str) -> dict:
    try:
        value = json.loads(archive.read(info))
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ProjectArchiveError(f'Invalid {label}') from exc
    if not isinstance(value, dict):
        raise ProjectArchiveError(f'Invalid {label}')
    return value


def _validate_manifest(manifest: dict) -> set[str]:
    required_objects = ('area', 'drawing_set', 'composition')
    required_lists = ('regions', 'field_masks', 'versions')
    if not isinstance(manifest.get('name'), str):
        raise ProjectArchiveError('Invalid project manifest name')
    if any(not isinstance(manifest.get(key), dict) for key in required_objects):
        raise ProjectArchiveError('Invalid project manifest object')
    if any(not isinstance(manifest.get(key, []), list) for key in required_lists):
        raise ProjectArchiveError('Invalid project manifest list')
    if not isinstance(manifest['composition'].get('layers', []), list):
        raise ProjectArchiveError('Invalid project composition layers')
    try:
        return _referenced_asset_paths(manifest)
    except (TypeError, AttributeError, ValueError) as exc:
        raise ProjectArchiveError('Invalid project asset path') from exc


def _extract_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with archive.open(info) as source, destination.open('wb') as target:
            while True:
                chunk = source.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_ENTRY_BYTES or written > info.file_size:
                    raise ProjectArchiveError(f'Archive entry exceeded declared size: {info.filename}', 413)
                target.write(chunk)
    except zipfile.BadZipFile as exc:
        raise ProjectArchiveError(f'Corrupt archive entry: {info.filename}') from exc
    if written != info.file_size:
        raise ProjectArchiveError(f'Archive entry size mismatch: {info.filename}')


def import_project_archive(stream: BinaryIO) -> Project:
    project_mod.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    upload = _read_upload(stream)
    staging = Path(tempfile.mkdtemp(prefix='.import-', dir=project_mod.PROJECTS_DIR))
    destination: Path | None = None
    try:
        try:
            archive = zipfile.ZipFile(upload)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ProjectArchiveError('Invalid project archive') from exc
        with archive:
            infos = _validated_infos(archive)
            if set(('archive.json', 'project.json')) - infos.keys():
                raise ProjectArchiveError('Project archive is missing root metadata')
            metadata = _read_json(archive, infos['archive.json'], 'archive metadata')
            if metadata.get('format_version') != ARCHIVE_FORMAT_VERSION:
                raise ProjectArchiveError('Unsupported project archive version')
            manifest = _read_json(archive, infos['project.json'], 'project manifest')
            assets = _validate_manifest(manifest)
            expected = {'archive.json', 'project.json', *assets}
            extra = set(infos) - expected
            missing = expected - set(infos)
            if extra:
                raise ProjectArchiveError(f'Unreferenced archive file: {sorted(extra)[0]}')
            if missing:
                raise ProjectArchiveError(f'Missing project asset: {sorted(missing)[0]}')
            new_id = uuid.uuid4().hex[:10]
            while (project_mod.PROJECTS_DIR / new_id).exists():
                new_id = uuid.uuid4().hex[:10]
            manifest['id'] = new_id
            for relative in sorted(assets):
                _extract_entry(archive, infos[relative], staging / relative)
            (staging / 'project.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            destination = project_mod.PROJECTS_DIR / new_id
            staging.rename(destination)
        try:
            return Project.load(destination.name)
        except Exception as exc:
            shutil.rmtree(destination, ignore_errors=True)
            raise ProjectArchiveError('Invalid project data') from exc
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        upload.close()
```

- [ ] **Step 4: Hide staging directories from the project list**

```python
# engine/project.py, inside list_projects()
    for d in PROJECTS_DIR.iterdir():
        if d.name.startswith('.'):
            continue
        manifest = d / 'project.json'
```

- [ ] **Step 5: Add focused rejection tests for every security boundary**

```python
# append imports, helpers, and tests to tests/test_project_archive.py
from unittest import mock
from engine.project_archive import _entry_path

    def make_zip(self, entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> io.BytesIO:
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
        output.seek(0)
        return output

    def minimal_entries(self):
        manifest = {
            'id': 'old', 'name': 'Imported', 'image_name': '',
            'area': {}, 'drawing_set': {},
            'composition': {'layers': [], 'selected_layer_id': None},
            'regions': [], 'selected_region_id': None,
            'field_masks': [], 'pfm_id': 'spiral', 'params': {}, 'versions': [],
        }
        return [
            ('archive.json', json.dumps({'application': 'PlotterForge', 'format_version': 1}).encode()),
            ('project.json', json.dumps(manifest).encode()),
        ]

    def assert_rejected(self, entries, message: str, status_code: int = 400):
        with self.assertRaisesRegex(ProjectArchiveError, message) as raised:
            import_project_archive(self.make_zip(entries))
        self.assertEqual(raised.exception.status_code, status_code)

    def test_rejects_traversal_absolute_backslash_and_duplicate_paths(self):
        base = self.minimal_entries()
        self.assert_rejected(base + [('../escape', b'x')], 'Invalid project asset path')
        self.assert_rejected(base + [('/absolute', b'x')], 'Invalid project asset path')
        self.assert_rejected(base + [('bad\\path', b'x')], 'Invalid project asset path')
        self.assert_rejected(base + [('EXTRA', b'x'), ('extra', b'y')], 'Duplicate archive path')

    def test_rejects_encrypted_symlink_directory_and_unreferenced_entries(self):
        encrypted = zipfile.ZipInfo('secret')
        encrypted.flag_bits = 0x1
        symlink = zipfile.ZipInfo('link')
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        directory = zipfile.ZipInfo('folder/')
        with self.assertRaisesRegex(ProjectArchiveError, 'Encrypted'):
            _entry_path(encrypted)
        with self.assertRaisesRegex(ProjectArchiveError, 'Non-regular'):
            _entry_path(symlink)
        with self.assertRaisesRegex(ProjectArchiveError, 'Directory'):
            _entry_path(directory)
        self.assert_rejected(self.minimal_entries() + [('orphan.bin', b'x')], 'Unreferenced')

    def test_rejects_corrupt_metadata_manifest_missing_asset_and_limits(self):
        self.assert_rejected([('archive.json', b'{'), ('project.json', b'{}')], 'Invalid archive metadata')
        self.assert_rejected([
            ('archive.json', json.dumps({'format_version': 99}).encode()),
            ('project.json', b'{}'),
        ], 'Unsupported project archive version')
        entries = self.minimal_entries()
        manifest = json.loads(entries[1][1])
        manifest['image_name'] = 'source.png'
        entries[1] = ('project.json', json.dumps(manifest).encode())
        self.assert_rejected(entries, 'Missing project asset')
        invalid = self.minimal_entries()
        invalid[1] = ('project.json', json.dumps({'name': 7}).encode())
        self.assert_rejected(invalid, 'Invalid project manifest')
        with mock.patch('engine.project_archive.MAX_UPLOAD_BYTES', 2):
            with self.assertRaisesRegex(ProjectArchiveError, 'exceeds 512 MiB') as raised:
                import_project_archive(io.BytesIO(b'xxx'))
            self.assertEqual(raised.exception.status_code, 413)
        with mock.patch('engine.project_archive.MAX_ENTRIES', 1):
            self.assert_rejected(self.minimal_entries(), 'more than 10000 entries', 413)
        with mock.patch('engine.project_archive.MAX_TOTAL_BYTES', 1):
            self.assert_rejected(self.minimal_entries(), 'expands beyond 1 GiB', 413)
        with mock.patch('engine.project_archive.MAX_ENTRY_BYTES', 2):
            self.assert_rejected(self.minimal_entries() + [('orphan.bin', b'xxx')], 'exceeds 256 MiB', 413)
```

Also add `import stat`. Keep the expected public message fixed even when tests lower the numeric constant.

- [ ] **Step 6: Run archive and existing project model tests**

Run: `.venv/bin/python -m pytest tests/test_project_archive.py tests/test_projects.py -q`

Expected: all tests pass; no `.import-*` directory remains in the temporary Projects directory.

- [ ] **Step 7: Commit secure import**

```bash
git add engine/project_archive.py engine/project.py tests/test_project_archive.py
git commit -m "feat: securely import project archives"
```

---

### Task 3: Project Archive HTTP Endpoints

**Files:**
- Modify: `web/server.py:1-30,2047-2103`
- Modify: `tests/test_projects.py`

**Interfaces:**
- Consumes: `build_project_archive`, `archive_filename`, `import_project_archive`, `ProjectArchiveError`, and `ARCHIVE_MIMETYPE` from Tasks 1-2.
- Produces: `GET /api/projects/<pid>/archive` and multipart `POST /api/projects/import`, both serialized by `_operation_lock` and compatible with the existing project payload shape.

- [ ] **Step 1: Add failing route tests for export, import, busy state, and atomic failure**

```python
# tests/test_projects.py imports
import io
import zipfile
from engine.project_archive import build_project_archive

# append to ProjectsApiTest
    def test_export_endpoint_returns_named_project_archive(self):
        response = self.client.get(f'/api/projects/{server._project.id}/archive')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/vnd.plotterforge.project+zip')
        self.assertIn('Start.plotter-project', response.headers['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertIn('project.json', archive.namelist())

    def test_import_endpoint_creates_and_opens_new_project(self):
        original = server._project
        archive = build_project_archive(original)
        response = self.client.post(
            '/api/projects/import',
            data={'file': (archive, 'saved.plotter-project')},
            content_type='multipart/form-data',
        )
        body = response.get_json()
        self.assertEqual(response.status_code, 200, body)
        self.assertNotEqual(body['current']['id'], original.id)
        self.assertEqual(body['current']['name'], original.name)
        self.assertEqual(server._project.id, body['current']['id'])

    def test_import_failure_preserves_current_project_and_project_list(self):
        current_id = server._project.id
        before = [project['id'] for project in project_mod.list_projects()]
        response = self.client.post(
            '/api/projects/import',
            data={'file': (io.BytesIO(b'broken'), 'broken.plotter-project')},
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(server._project.id, current_id)
        self.assertEqual([project['id'] for project in project_mod.list_projects()], before)

    def test_archive_transfer_is_blocked_while_processing(self):
        server._process_thread = AliveThread()
        export = self.client.get(f'/api/projects/{server._project.id}/archive')
        imported = self.client.post(
            '/api/projects/import',
            data={'file': (io.BytesIO(b'broken'), 'broken.plotter-project')},
            content_type='multipart/form-data',
        )
        self.assertEqual(export.status_code, 409)
        self.assertEqual(imported.status_code, 409)
```

- [ ] **Step 2: Run route tests and verify 404 failures**

Run: `.venv/bin/python -m pytest tests/test_projects.py -q`

Expected: four new tests fail because the routes do not exist.

- [ ] **Step 3: Add imports and the export route**

```python
# web/server.py imports
from engine.project_archive import (
    ARCHIVE_MIMETYPE,
    ProjectArchiveError,
    archive_filename,
    build_project_archive,
    import_project_archive,
)


@app.route('/api/projects/<pid>/archive')
def api_project_archive_export(pid):
    with _operation_lock:
        blocked = _project_transition_blocked()
        if blocked:
            return blocked
        manifest = project_mod.PROJECTS_DIR / pid / 'project.json'
        if not manifest.exists():
            return jsonify(error='Unknown project'), 404
        project = _project if pid == _project.id else Project.load(pid)
        try:
            payload = build_project_archive(project)
        except ValueError:
            return jsonify(error='Project contains missing or invalid assets'), 400
        return send_file(
            payload,
            mimetype=ARCHIVE_MIMETYPE,
            as_attachment=True,
            download_name=archive_filename(project),
        )
```

- [ ] **Step 4: Add the atomic import route and status translation**

```python
@app.route('/api/projects/import', methods=['POST'])
def api_project_archive_import():
    with _operation_lock:
        blocked = _project_transition_blocked()
        if blocked:
            return blocked
        upload = request.files.get('file')
        if upload is None:
            return jsonify(error='No project archive provided'), 400
        try:
            project = import_project_archive(upload.stream)
        except ProjectArchiveError as exc:
            return jsonify(error=str(exc)), exc.status_code
        except OSError:
            return jsonify(error='Could not import project archive'), 500
        _switch_project(project.id)
        return jsonify(
            ok=True,
            current=_project_public(_project),
            projects=project_mod.list_projects(),
        )
```

- [ ] **Step 5: Run the route and archive suites**

Run: `.venv/bin/python -m pytest tests/test_projects.py tests/test_project_archive.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit HTTP support**

```bash
git add web/server.py tests/test_projects.py
git commit -m "feat: expose project archive endpoints"
```

---

### Task 4: Save/Open Project File UI

**Files:**
- Modify: `frontend/src/lib/state.svelte.ts:20-25,115-125`
- Modify: `frontend/src/lib/api.ts:1-30,210-255`
- Modify: `frontend/src/components/MenuBar.svelte`
- Modify: `frontend/src/App.svelte:20-65,150-165`

**Interfaces:**
- Consumes: Task 3 archive routes and the existing `switchProject(payload, generation)` flow.
- Produces: `api.saveProjectFile(): Promise<void>`, `api.openProjectFile(file: File): Promise<boolean>`, `studio.projectFileBusy`, and the Project menu actions.

- [ ] **Step 1: Add a failing browser test for menu affordances before wiring behavior**

```typescript
// append to frontend/e2e/a-projects.spec.ts
test("A7: Project menu exposes portable Save and Open actions", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "Portable UI");
  await gotoApp(page);
  await page.getByRole("button", { name: "Project" }).click();
  await expect(page.getByRole("button", { name: "Save project file…" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Open project file…" })).toBeEnabled();
});
```

- [ ] **Step 2: Run the focused browser test and verify the actions are absent**

Run: `cd frontend && E2E_BACKEND_CMD='.venv/bin/python -m web.server' npx playwright test e2e/a-projects.spec.ts --grep 'A7' --reporter=list`

Expected: fail because neither button exists. If the sandbox blocks local port binding, rerun the same command with approved local-server permissions.

- [ ] **Step 3: Add transfer state and reusable frontend download helpers**

```typescript
// frontend/src/lib/state.svelte.ts, projects state
  projectFileBusy = $state(false);
```

```typescript
// frontend/src/lib/api.ts, near jget/jpost
function responseFilename(response: Response, fallback: string) {
  const disposition = response.headers.get("content-disposition") ?? "";
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const candidate = utf8 ? decodeURIComponent(utf8) : plain;
  return candidate?.trim() || fallback;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Implement archive save and import through the existing switch path**

```typescript
// frontend/src/lib/api.ts, inside api after deleteProject
  async saveProjectFile() {
    const current = studio.currentProject;
    if (!current || studio.projectFileBusy) return;
    studio.projectFileBusy = true;
    studio.status = "Saving project…";
    try {
      const response = await fetch(`/api/projects/${current.id}/archive`);
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail?.error || `HTTP ${response.status}`);
      }
      const fallback = `${current.name || "project"}.plotter-project`;
      downloadBlob(await response.blob(), responseFilename(response, fallback));
      studio.status = "Project saved";
      pushLog(`Saved project ${current.name}`);
    } catch (error) {
      reportError("Save project failed", error);
    } finally {
      studio.projectFileBusy = false;
    }
  },

  async openProjectFile(file: File) {
    if (studio.projectFileBusy) return false;
    const generation = beginProjectGeneration();
    studio.projectFileBusy = true;
    studio.status = "Opening project…";
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch("/api/projects/import", { method: "POST", body });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
      if (!isCurrentProject(generation)) return false;
      const ready = await this.switchProject(payload, generation);
      if (ready) {
        studio.status = "Ready";
        pushLog(`Opened project ${payload.current.name}`);
      }
      return ready;
    } catch (error) {
      if (isCurrentProject(generation)) reportError("Open project failed", error);
      return false;
    } finally {
      if (isCurrentProject(generation)) studio.projectFileBusy = false;
    }
  },
```

- [ ] **Step 5: Add the Project menu actions**

```svelte
<!-- frontend/src/components/MenuBar.svelte props -->
let {
  onImport,
  onOpenProject,
  onPlot,
}: {
  onImport: () => void;
  onOpenProject: () => void;
  onPlot: () => void;
} = $props();
```

```svelte
<!-- Project menu, immediately after New project… -->
<button
  onclick={() => run(onOpenProject)}
  disabled={studio.projectFileBusy}
>Open project file…</button>
<button
  onclick={() => run(() => void api.saveProjectFile())}
  disabled={!studio.currentProject || studio.projectFileBusy}
>Save project file…</button>
```

- [ ] **Step 6: Add a separate hidden project-file picker in App**

```typescript
// frontend/src/App.svelte script
let projectFileInput: HTMLInputElement;

function pickProjectFile() {
  projectFileInput.click();
}

async function onProjectFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) await api.openProjectFile(file);
  input.value = "";
}
```

```svelte
<!-- App menu -->
<MenuBar onImport={pickImage} onOpenProject={pickProjectFile} onPlot={() => selectStep("plot")} />

<!-- beside the existing hidden image input -->
<input
  bind:this={projectFileInput}
  type="file"
  accept=".plotter-project,application/vnd.plotterforge.project+zip,application/zip"
  onchange={onProjectFile}
  style="display:none"
/>
```

- [ ] **Step 7: Run type/build checks and the menu test**

Run: `cd frontend && npm run build`

Expected: build succeeds. Existing unrelated Svelte warnings may remain, but no new warning references the changed files.

Run: `cd frontend && E2E_BACKEND_CMD='.venv/bin/python -m web.server' E2E_SKIP_BUILD=1 npx playwright test e2e/a-projects.spec.ts --grep 'A7' --reporter=list`

Expected: `1 passed`.

- [ ] **Step 8: Commit the UI slice**

```bash
git add frontend/src/lib/state.svelte.ts frontend/src/lib/api.ts frontend/src/components/MenuBar.svelte frontend/src/App.svelte frontend/e2e/a-projects.spec.ts web/static/app
git commit -m "feat: add project archive save and open controls"
```

---

### Task 5: Full Browser Round-Trip, Failure UX, and Final Verification

**Files:**
- Modify: `frontend/e2e/a-projects.spec.ts`
- Modify: generated files under `web/static/app/` only if the final build changes them.

**Interfaces:**
- Consumes: all prior backend and frontend interfaces.
- Produces: regression coverage proving portable project download/import, duplicate imports, restored editable state, and controlled invalid-file errors.

- [ ] **Step 1: Add failing end-to-end round-trip and invalid-archive tests**

```typescript
// frontend/e2e/a-projects.spec.ts imports
import { join } from "path";
import { writeFileSync } from "fs";
import { getComposition } from "./fixtures";

test("A8: saved project file reopens as an editable independent project", async ({ page, request, baseURL }, testInfo) => {
  await freshProject(request, baseURL!, "Portable Round Trip");
  await gotoApp(page);
  await page.locator('input[type="file"][accept="image/*,.svg"]').setInputFiles(join(ASSETS, "sample.svg"));
  const before = await getComposition(request, baseURL!);

  await page.getByRole("button", { name: "Project" }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Save project file…" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("Portable-Round-Trip.plotter-project");
  const archivePath = testInfo.outputPath("portable.plotter-project");
  await download.saveAs(archivePath);

  await freshProject(request, baseURL!, "Temporary Current");
  await page.reload();
  await expect(page.locator(".menubar")).toContainText("Temporary Current");
  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Open project file…" }).click();
  await page.locator('input[type="file"][accept*=".plotter-project"]').setInputFiles(archivePath);
  await expect(page.locator(".menubar")).toContainText("Portable Round Trip", { timeout: 20_000 });
  const firstImport = await (await request.get(`${baseURL}/api/projects`)).json();
  const firstId = firstImport.current.id;
  const after = await getComposition(request, baseURL!);
  expect(after.layers.map((layer) => layer.svg)).toEqual(before.layers.map((layer) => layer.svg));

  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Open project file…" }).click();
  await page.locator('input[type="file"][accept*=".plotter-project"]').setInputFiles(archivePath);
  const secondImport = await (await request.get(`${baseURL}/api/projects`)).json();
  expect(secondImport.current.id).not.toBe(firstId);
  expect(secondImport.current.name).toBe("Portable Round Trip");
});

test("A9: invalid project file reports an error without switching", async ({ page, request, baseURL }, testInfo) => {
  await freshProject(request, baseURL!, "Safe Current");
  await gotoApp(page);
  const invalidPath = testInfo.outputPath("invalid.plotter-project");
  writeFileSync(invalidPath, "not a zip");

  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Open project file…" }).click();
  await page.locator('input[type="file"][accept*=".plotter-project"]').setInputFiles(invalidPath);

  await expect(page.locator(".status .log")).toContainText("Open project failed: Invalid project archive");
  await expect(page.locator(".menubar")).toContainText("Safe Current");
});
```

Update the existing import line to include `ASSETS` and `getComposition` from `./fixtures`; do not leave duplicate imports.

- [ ] **Step 2: Run A8/A9 against the completed UI and backend**

Run: `cd frontend && E2E_BACKEND_CMD='.venv/bin/python -m web.server' E2E_SKIP_BUILD=1 npx playwright test e2e/a-projects.spec.ts --grep 'A8|A9' --reporter=list`

Expected: `2 passed`. The tests use visible project-name assertions as their synchronization boundary and contain no fixed sleeps.

- [ ] **Step 3: Run all focused backend and project browser tests**

Run: `.venv/bin/python -m pytest tests/test_project_archive.py tests/test_projects.py tests/test_versions.py -q`

Expected: all tests pass.

Run: `cd frontend && E2E_BACKEND_CMD='.venv/bin/python -m web.server' E2E_SKIP_BUILD=1 npx playwright test e2e/a-projects.spec.ts e2e/n-project-lifecycle.spec.ts e2e/i-versions.spec.ts --reporter=list`

Expected: all tests pass.

- [ ] **Step 4: Rebuild and inspect the final diff**

Run: `cd frontend && npm run build`

Expected: build succeeds and updates only the hashed frontend bundle reference/assets.

Run: `git diff --check && git status --short && git diff --stat`

Expected: no whitespace errors; only planned source, tests, and generated frontend assets are modified. Preserve the unrelated untracked `.agents/` directory.

- [ ] **Step 5: Commit final journey coverage and generated bundle**

```bash
git add frontend/e2e/a-projects.spec.ts web/static/app
git commit -m "test: cover portable project round trips"
```

- [ ] **Step 6: Final verification before completion**

Run: `.venv/bin/python -m pytest tests/test_project_archive.py tests/test_projects.py tests/test_versions.py -q`

Run: `cd frontend && E2E_BACKEND_CMD='.venv/bin/python -m web.server' E2E_SKIP_BUILD=1 npx playwright test e2e/a-projects.spec.ts e2e/n-project-lifecycle.spec.ts e2e/i-versions.spec.ts --reporter=list`

Run: `cd frontend && npm run build`

Expected: all Python tests and browser tests pass; the production build exits zero. Report the separate pre-existing `ParamControl.svelte` diagnostics if `npm run check` remains red, without attributing them to this feature.
