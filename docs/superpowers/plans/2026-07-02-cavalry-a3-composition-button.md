# Cavalry A3 Composition Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bridge-window button that creates and activates a 2970 × 4200 px portrait Cavalry composition for A3 plotting at 10 px/mm.

**Architecture:** Keep the feature entirely inside the existing Cavalry UI script. The button uses Cavalry's composition APIs, while the existing `onCompChanged` callback sends the newly active composition through the live bridge.

**Tech Stack:** Cavalry JavaScript UI/API, Python `unittest` contract tests, Node.js syntax validation.

---

### Task 1: Add and install the A3 composition button

**Files:**
- Modify: `tests/test_cavalry_bridge.py`
- Modify: `cavalry/plotter-bridge.js`
- Install copy: `C:\Users\Adrien\AppData\Roaming\Cavalry\Scripts\plotter-bridge.js`

- [ ] **Step 1: Write the failing script contract test**

Add this method to `CavalryScriptContractTest`:

```python
def test_creates_and_activates_portrait_a3_composition(self):
    self.assertIn('var createA3 = new ui.Button("New A3 Composition");', self.script)
    self.assertIn('var compId = api.createComp("A3 Plotter · 10 px/mm");', self.script)
    self.assertIn('api.set(compId, { resolution: [2970, 4200] });', self.script)
    self.assertIn("api.setActiveComp(compId);", self.script)
    self.assertIn("ui.add(createA3);", self.script)
    self.assertIn('status.setText("Could not create A3 composition");', self.script)
    self.assertIn("console.error(e);", self.script)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
uv run python -m pytest tests/test_cavalry_bridge.py::CavalryScriptContractTest::test_creates_and_activates_portrait_a3_composition -q
```

Expected: FAIL because the button and composition API calls are absent.

- [ ] **Step 3: Implement the button**

Add this UI code after the live checkbox row is built and before `ui.show()`:

```javascript
var createA3 = new ui.Button("New A3 Composition");
createA3.onClick = function () {
  try {
    var compId = api.createComp("A3 Plotter · 10 px/mm");
    api.set(compId, { resolution: [2970, 4200] });
    api.setActiveComp(compId);
    status.setText("Created A3 · 2970 × 4200 px");
  } catch (e) {
    status.setText("Could not create A3 composition");
    console.error(e);
  }
};

ui.add(row);
ui.add(createA3);
ui.add(status);
ui.show();
```

- [ ] **Step 4: Run focused and full verification**

Run:

```powershell
uv run python -m pytest tests/test_cavalry_bridge.py::CavalryScriptContractTest -q
node --check cavalry/plotter-bridge.js
uv run python -m pytest tests -q
```

Expected: all script contract tests pass, syntax validation exits 0, and the full suite has no failures.

- [ ] **Step 5: Update and verify the installed script**

Copy `cavalry/plotter-bridge.js` to `C:\Users\Adrien\AppData\Roaming\Cavalry\Scripts\plotter-bridge.js`, then compare SHA-256 hashes. Expected: hashes match.
