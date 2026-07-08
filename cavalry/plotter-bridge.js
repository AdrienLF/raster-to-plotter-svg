// Cavalry → Plotter Studio live bridge.
//
// Install: copy this file into Cavalry's Scripts folder
// (Help ▸ Show Scripts Folder), then open it via Window ▸ Scripts ▸ plotter-bridge.
// While the window is open, every debounced scene change exports the current
// frame as SVG and posts it to the plotter app, which keeps a "Cavalry Live"
// layer in sync on the A3 preview.
//
// Requires the plotter app running (start-studio.bat, port 7438).

var SERVER = "http://localhost:7438";
var DEBOUNCE_MS = 500;
// renderSVGFrame appends the .svg extension itself.
var TMP_SVG_STEM = api.getTempFolder() + "/cavalry-live-bridge";
var TMP_SVG = TMP_SVG_STEM + ".svg";

// New script window = new session. The app uses this to detect "Cavalry was
// reopened" and asks whether to keep capturing into the existing layer or
// start a new one.
var SESSION = Math.random().toString(16).slice(2) + Date.now().toString(16);

var client = new api.WebClient(SERVER);
client.addHeader("X-Cavalry-Session", SESSION);

ui.setTitle("Plotter Bridge");
var enabled = new ui.Checkbox(true);
var status = new ui.Label("Waiting for changes…");
var row = new ui.HLayout();
row.add(enabled);
row.add(new ui.Label("Live"));

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

// ── Tessellation authoring ──────────────────────────────────────────────────
// Bind up to 16 selected numeric attributes to a light/dark boundary, choose
// a repeat lattice, and bake a 32-state sweep into a reusable Plotter Studio
// tessellation pattern (see docs/superpowers/plans/2026-07-08-cavalry-tessellation-authoring.md).
var MAX_BINDINGS = 16;
var STATE_COUNT = 32;

ui.add(new ui.Label("— Tessellation —"));

var patternName = new ui.LineEdit();
var patternNameRow = new ui.HLayout();
patternNameRow.add(new ui.Label("Name"));
patternNameRow.add(patternName);
ui.add(patternNameRow);

var latticePreset = new ui.DropDown();
latticePreset.addEntry("Rectangular");
latticePreset.addEntry("Brick");
latticePreset.addEntry("Hex/Isometric");
latticePreset.addEntry("Custom");

var latticeRow = new ui.HLayout();
latticeRow.add(new ui.Label("Lattice"));
latticeRow.add(latticePreset);
ui.add(latticeRow);

var customAx = new ui.NumericField(100);
var customAy = new ui.NumericField(0);
var customBx = new ui.NumericField(0);
var customBy = new ui.NumericField(100);

var customRow = new ui.HLayout();
customRow.add(new ui.Label("A"));
customRow.add(customAx);
customRow.add(customAy);
customRow.add(new ui.Label("B"));
customRow.add(customBx);
customRow.add(customBy);
ui.add(customRow);

// Rows created by "Add selected parameter"; each entry keeps the widgets it
// owns so removal/rebuild can reparent them without losing edited values.
var bindings = [];
var bindingsPanel = new ui.VLayout();
var bindingsScroll = new ui.ScrollView();
bindingsScroll.setLayout(bindingsPanel);
ui.add(bindingsScroll);

function rebuildBindingsLayout() {
  bindingsPanel = new ui.VLayout();
  bindings.forEach(function (binding) {
    bindingsPanel.add(binding.row);
  });
  bindingsScroll.setLayout(bindingsPanel);
}

var tessStatus = new ui.Label("Select one numeric attribute, then add it.");

var addBinding = new ui.Button("Add selected parameter");
addBinding.onClick = function () {
  var attrs = api.getSelectedAttributes();
  if (!attrs || attrs.length !== 1) {
    tessStatus.setText("Select exactly one attribute to add.");
    return;
  }
  if (bindings.length >= MAX_BINDINGS) {
    tessStatus.setText("Maximum of " + MAX_BINDINGS + " bound parameters reached.");
    return;
  }

  var layerId = attrs[0].layerId;
  var attrId = attrs[0].attrId;
  var isDuplicate = bindings.some(function (existing) {
    return existing.layerId === layerId && existing.attrId === attrId;
  });
  if (isDuplicate) {
    tessStatus.setText("That attribute is already bound.");
    return;
  }

  var value = api.get(layerId, attrId);
  if (typeof value !== "number" || !isFinite(value)) {
    tessStatus.setText("Selected attribute is not a finite number.");
    return;
  }

  var label = new ui.Label(api.getNiceName(layerId) + " · " + attrId);
  var lightField = new ui.NumericField(value);
  var darkField = new ui.NumericField(value);
  var removeButton = new ui.Button("Remove");

  var row = new ui.HLayout();
  row.add(label);
  row.add(new ui.Label("Light"));
  row.add(lightField);
  row.add(new ui.Label("Dark"));
  row.add(darkField);
  row.add(removeButton);

  var binding = {
    layerId: layerId,
    attrId: attrId,
    label: label,
    lightField: lightField,
    darkField: darkField,
    row: row,
    curve: null,
  };

  removeButton.onClick = function () {
    var index = bindings.indexOf(binding);
    if (index !== -1) {
      bindings.splice(index, 1);
    }
    rebuildBindingsLayout();
    tessStatus.setText(bindings.length + " of " + MAX_BINDINGS + " parameters bound.");
  };

  bindings.push(binding);
  rebuildBindingsLayout();
  tessStatus.setText(bindings.length + " of " + MAX_BINDINGS + " parameters bound.");
};
ui.add(addBinding);
ui.add(tessStatus);

function computeLattice() {
  var resolution = api.get(api.getActiveComp(), "resolution");
  var width = resolution[0];
  var height = resolution[1];
  var preset = latticePreset.getValue();
  if (preset === "Rectangular") {
    return { a: [width, 0], b: [0, height] };
  }
  if (preset === "Brick") {
    return { a: [width, 0], b: [width / 2, height] };
  }
  if (preset === "Hex/Isometric") {
    return { a: [width, 0], b: [width / 2, height * 0.8660254038] };
  }
  return {
    a: [customAx.getValue(), customAy.getValue()],
    b: [customBx.getValue(), customBy.getValue()],
  };
}

ui.show();

function push() {
  try {
    // All expensive work happens here, on the debounce trailing edge —
    // never inside a change callback.
    api.renderSVGFrame(TMP_SVG_STEM, 100, false);
    client.postFromFile("/api/cavalry", TMP_SVG, "image/svg+xml"); // blocking, ~ms on localhost
    if (client.status() === 200) {
      status.setText("Sent frame " + api.getFrame());
    } else if (client.status() === 202) {
      status.setText("Waiting — choose in Plotter Studio (continue or new layer)");
    } else {
      status.setText("Server error " + client.status());
    }
  } catch (e) {
    // Server down or render failed: show once, stay quiet until next change.
    status.setText("Plotter app offline (start-studio.bat)");
  }
}

// Trailing-edge debounce: every scene event restarts a one-shot timer.
var timer = new api.Timer({
  onTimeout: function () {
    push();
  },
});
timer.setRepeating(false);
timer.setInterval(DEBOUNCE_MS);

function poke() {
  if (!enabled.getValue()) return;
  timer.stop();
  timer.start();
}

ui.addCallbackObject({
  onAttrChanged: function (layerId, attrId) {
    poke();
  },
  onLayerAdded: function (layerId) {
    poke();
  },
  onLayerRemoved: function (layerId) {
    poke();
  },
  onSceneChanged: function () {
    poke();
  },
  onCompChanged: function () {
    poke();
  },
});
