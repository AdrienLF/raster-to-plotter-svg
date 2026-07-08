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

// Tessellation authoring ----------------------------------------------------

var tessellationLayout = new ui.VLayout();
tessellationLayout.addSeparator("Tessellation");

var patternName = new ui.LineEdit();
patternName.setPlaceholder("Pattern name");

var latticePreset = new ui.DropDown();
latticePreset.addEntry("Rectangular");
latticePreset.addEntry("Brick");
latticePreset.addEntry("Hex/Isometric");
latticePreset.addEntry("Custom");
latticePreset.setValue(0);

var latticeWidth = new ui.NumericField(100);
var latticeHeight = new ui.NumericField(100);
var customAx = new ui.NumericField(100);
var customAy = new ui.NumericField(0);
var customBx = new ui.NumericField(0);
var customBy = new ui.NumericField(100);

var nameRow = new ui.HLayout();
nameRow.add(new ui.Label("Name"), patternName);
var presetRow = new ui.HLayout();
presetRow.add(
  new ui.Label("Lattice"),
  latticePreset,
  new ui.Label("W"),
  latticeWidth,
  new ui.Label("H"),
  latticeHeight
);
var customRow = new ui.HLayout();
customRow.add(
  new ui.Label("Custom A"),
  customAx,
  customAy,
  new ui.Label("B"),
  customBx,
  customBy
);

var bindings = [];
var bindingLayout = new ui.VLayout();
var bindingScroll = new ui.ScrollView();
bindingScroll.setLayout(bindingLayout);
bindingScroll.setFixedHeight(160);

function rebuildBindings() {
  bindingLayout.clear();
  if (bindings.length === 0) {
    bindingLayout.add(new ui.Label("Select one numeric attribute, then add it."));
    return;
  }
  for (var index = 0; index < bindings.length; index++) {
    (function (bindingIndex) {
      var binding = bindings[bindingIndex];
      var bindingRow = new ui.HLayout();
      var value = binding.light;
      var lightField = new ui.NumericField(value);
      value = binding.dark;
      var darkField = new ui.NumericField(value);
      var removeBinding = new ui.Button("Remove");
      lightField.onValueChanged = function () {
        binding.light = lightField.getValue();
      };
      darkField.onValueChanged = function () {
        binding.dark = darkField.getValue();
      };
      removeBinding.onClick = function () {
        bindings.splice(bindingIndex, 1);
        rebuildBindings();
      };
      bindingRow.add(
        new ui.Label(api.getNiceName(binding.layerId) + " · " + binding.attrId),
        new ui.Label("Light"),
        lightField,
        new ui.Label("Dark"),
        darkField,
        removeBinding
      );
      bindingLayout.add(bindingRow);
    })(index);
  }
}

var addBinding = new ui.Button("Add selected parameter");
addBinding.onClick = function () {
  try {
    var selectedAttributes = api.getSelectedAttributes();
    if (!selectedAttributes || selectedAttributes.length !== 1) {
      status.setText("Select exactly one numeric attribute");
      return;
    }
    if (bindings.length >= 16) {
      status.setText("A tessellation can use at most 16 parameters");
      return;
    }
    var layerId = selectedAttributes[0][0];
    var attrId = selectedAttributes[0][1];
    var value = api.get(layerId, attrId);
    if (typeof value !== "number" || !isFinite(value)) {
      status.setText("The selected attribute is not a finite number");
      return;
    }
    for (var index = 0; index < bindings.length; index++) {
      if (bindings[index].layerId === layerId && bindings[index].attrId === attrId) {
        status.setText("That parameter is already linked");
        return;
      }
    }
    bindings.push({
      layerId: layerId,
      attrId: attrId,
      light: value,
      dark: value,
      curve: null,
    });
    rebuildBindings();
    status.setText("Added " + api.getNiceName(layerId) + " · " + attrId);
  } catch (e) {
    status.setText("Could not read the selected attribute");
    console.error(e);
  }
};

function compositionResolution() {
  return api.get(api.getActiveComp(), "resolution");
}

var bakeProgress = new ui.ProgressBar();
bakeProgress.setMaximum(32);
bakeProgress.setValue(0);

rebuildBindings();
tessellationLayout.add(
  nameRow,
  presetRow,
  customRow,
  addBinding,
  bindingScroll,
  bakeProgress
);

ui.add(row);
ui.add(createA3);
ui.add(status);
ui.add(tessellationLayout);
ui.setMinimumWidth(540);
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
