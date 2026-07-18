// Cavalry → PlotterForge live bridge.
//
// Install: copy this file into Cavalry's Scripts folder
// (Help ▸ Show Scripts Folder), then open it via Window ▸ Scripts ▸ plotter-bridge.
// While the window is open, every debounced scene change exports the current
// frame as SVG and posts it to the plotter app, which keeps a "Cavalry Live"
// layer in sync on the A3 preview.
//
// Requires the plotter app running (start-windows.bat, port 7438).

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

function latticeVectors() {
  var width = latticeWidth.getValue();
  var height = latticeHeight.getValue();
  var preset = latticePreset.getText();
  if (preset === "Brick") {
    return { a: [width, 0], b: [width / 2, height] };
  }
  if (preset === "Hex/Isometric") {
    return { a: [width, 0], b: [width / 2, height * 0.8660254038] };
  }
  if (preset === "Custom") {
    return {
      a: [customAx.getValue(), customAy.getValue()],
      b: [customBx.getValue(), customBy.getValue()],
    };
  }
  return { a: [width, 0], b: [0, height] };
}

function responseError(fallback) {
  var body = client.body();
  if (!body) return fallback;
  try {
    var parsed = JSON.parse(body);
    return parsed.error || body;
  } catch (e) {
    return body;
  }
}

function restoreBindings(originalValues) {
  for (var index = 0; index < originalValues.length; index++) {
    var original = originalValues[index];
    var values = {};
    values[original.attrId] = original.value;
    try {
      api.set(original.layerId, values);
    } catch (e) {
      console.error(e);
    }
  }
}

function bakePattern() {
  var originalValues = [];
  try {
    var name = patternName.getText().trim();
    if (name.length < 1 || name.length > 80) {
      status.setText("Pattern name must contain 1–80 characters");
      return;
    }
    if (bindings.length === 0) {
      status.setText("Add at least one numeric parameter");
      return;
    }

    var vectors = latticeVectors();
    var allNumbers = vectors.a.concat(vectors.b);
    for (var vectorIndex = 0; vectorIndex < allNumbers.length; vectorIndex++) {
      if (
        typeof allNumbers[vectorIndex] !== "number" ||
        !isFinite(allNumbers[vectorIndex])
      ) {
        status.setText("Lattice vectors must contain finite numbers");
        return;
      }
    }
    var determinant = vectors.a[0] * vectors.b[1] - vectors.a[1] * vectors.b[0];
    if (!isFinite(determinant) || Math.abs(determinant) < 0.000000001) {
      status.setText("Lattice vectors must not be collinear");
      return;
    }

    var manifestBindings = [];
    for (var bindingIndex = 0; bindingIndex < bindings.length; bindingIndex++) {
      var candidate = bindings[bindingIndex];
      if (
        typeof candidate.light !== "number" ||
        !isFinite(candidate.light) ||
        typeof candidate.dark !== "number" ||
        !isFinite(candidate.dark)
      ) {
        status.setText("All Light and Dark values must be finite numbers");
        return;
      }
      manifestBindings.push({
        layer_id: candidate.layerId,
        attribute_id: candidate.attrId,
        light: candidate.light,
        dark: candidate.dark,
        curve: null,
      });
    }

    var resolution = compositionResolution();
    if (
      !resolution ||
      resolution.length !== 2 ||
      !isFinite(resolution[0]) ||
      !isFinite(resolution[1]) ||
      resolution[0] <= 0 ||
      resolution[1] <= 0
    ) {
      status.setText("The active composition has no valid resolution");
      return;
    }
    var manifest = {
      format_version: 1,
      name: name,
      lattice: vectors,
      bounds: [0, 0, resolution[0], resolution[1]],
      bindings: manifestBindings,
    };

    for (var originalIndex = 0; originalIndex < bindings.length; originalIndex++) {
      originalValues.push({
        layerId: bindings[originalIndex].layerId,
        attrId: bindings[originalIndex].attrId,
        value: api.get(
          bindings[originalIndex].layerId,
          bindings[originalIndex].attrId
        ),
      });
    }

    status.setText("Creating tessellation bake…");
    client.post("/api/tessellations/sessions", JSON.stringify(manifest), "application/json");
    if (client.status() !== 200) {
      throw new Error(responseError("Could not create tessellation session"));
    }
    var sessionId = JSON.parse(client.body()).session_id;
    if (!sessionId) {
      throw new Error("The server did not return a tessellation session");
    }

    for (var stateIndex = 0; stateIndex < 32; stateIndex++) {
      var t = stateIndex / 31;
      for (var linkedIndex = 0; linkedIndex < bindings.length; linkedIndex++) {
        var binding = bindings[linkedIndex];
        var stateValues = {};
        stateValues[binding.attrId] =
          binding.light + t * (binding.dark - binding.light);
        api.set(binding.layerId, stateValues);
      }
      var stateStem = api.getTempFolder() + "/plotter-tessellation-" + stateIndex;
      api.renderSVGFrame(stateStem, 100, true);
      var stateSvg = api.readFromFile(stateStem + '.svg');
      client.post(
        "/api/tessellations/sessions/" + sessionId + "/states/" + stateIndex,
        stateSvg,
        "image/svg+xml"
      );
      if (client.status() !== 200) {
        throw new Error(responseError("Could not upload state " + stateIndex));
      }
      bakeProgress.setValue(stateIndex + 1);
      status.setText("Baking state " + (stateIndex + 1) + " / 32");
    }

    client.post(
      "/api/tessellations/sessions/" + sessionId + "/finalize",
      "",
      "application/json"
    );
    if (client.status() !== 200) {
      throw new Error(responseError("Could not install tessellation"));
    }
    status.setText("Installed " + name);
  } catch (e) {
    status.setText(e && e.message ? e.message : String(e));
    console.error(e);
  } finally {
    restoreBindings(originalValues);
    bakeProgress.setValue(0);
  }
}

var bakeProgress = new ui.ProgressBar();
bakeProgress.setMaximum(32);
bakeProgress.setValue(0);
var bakeTessellation = new ui.Button("Bake tessellation");
bakeTessellation.onClick = function () {
  bakePattern();
};

// Dither shape authoring ------------------------------------------------------
// Bakes the current composition as a Shape Dither stamp: with linked
// parameters, 32 states are swept from their Light to Dark values (state 0 =
// highlight artwork, state 31 = shadow artwork); with none, a single static
// state is baked and PlotterForge carries tone by scaling alone. Shares the
// parameter list above with tessellation baking.

function bakeShape() {
  var originalValues = [];
  try {
    var name = shapeName.getText().trim();
    if (name.length < 1 || name.length > 80) {
      status.setText("Shape name must contain 1–80 characters");
      return;
    }

    var stateCount = bindings.length > 0 ? 32 : 1;
    for (var bindingIndex = 0; bindingIndex < bindings.length; bindingIndex++) {
      var candidate = bindings[bindingIndex];
      if (
        typeof candidate.light !== "number" ||
        !isFinite(candidate.light) ||
        typeof candidate.dark !== "number" ||
        !isFinite(candidate.dark)
      ) {
        status.setText("All Light and Dark values must be finite numbers");
        return;
      }
    }

    var resolution = compositionResolution();
    if (
      !resolution ||
      resolution.length !== 2 ||
      !isFinite(resolution[0]) ||
      !isFinite(resolution[1]) ||
      resolution[0] <= 0 ||
      resolution[1] <= 0
    ) {
      status.setText("The active composition has no valid resolution");
      return;
    }
    var manifest = {
      format_version: 1,
      name: name,
      state_count: stateCount,
      bounds: [0, 0, resolution[0], resolution[1]],
    };

    for (var originalIndex = 0; originalIndex < bindings.length; originalIndex++) {
      originalValues.push({
        layerId: bindings[originalIndex].layerId,
        attrId: bindings[originalIndex].attrId,
        value: api.get(
          bindings[originalIndex].layerId,
          bindings[originalIndex].attrId
        ),
      });
    }

    status.setText("Creating shape bake…");
    client.post("/api/shapes/sessions", JSON.stringify(manifest), "application/json");
    if (client.status() !== 200) {
      throw new Error(responseError("Could not create shape session"));
    }
    var sessionId = JSON.parse(client.body()).session_id;
    if (!sessionId) {
      throw new Error("The server did not return a shape session");
    }

    for (var stateIndex = 0; stateIndex < stateCount; stateIndex++) {
      var t = stateCount > 1 ? stateIndex / (stateCount - 1) : 0;
      for (var linkedIndex = 0; linkedIndex < bindings.length; linkedIndex++) {
        var binding = bindings[linkedIndex];
        var stateValues = {};
        stateValues[binding.attrId] =
          binding.light + t * (binding.dark - binding.light);
        api.set(binding.layerId, stateValues);
      }
      var stateStem = api.getTempFolder() + "/plotter-shape-" + stateIndex;
      api.renderSVGFrame(stateStem, 100, true);
      var stateSvg = api.readFromFile(stateStem + '.svg');
      client.post(
        "/api/shapes/sessions/" + sessionId + "/states/" + stateIndex,
        stateSvg,
        "image/svg+xml"
      );
      if (client.status() !== 200) {
        throw new Error(responseError("Could not upload state " + stateIndex));
      }
      bakeProgress.setValue(stateIndex + 1);
      status.setText("Baking shape state " + (stateIndex + 1) + " / " + stateCount);
    }

    client.post(
      "/api/shapes/sessions/" + sessionId + "/finalize",
      "",
      "application/json"
    );
    if (client.status() !== 200) {
      throw new Error(responseError("Could not install shape"));
    }
    status.setText("Installed shape " + name);
  } catch (e) {
    status.setText(e && e.message ? e.message : String(e));
    console.error(e);
  } finally {
    restoreBindings(originalValues);
    bakeProgress.setValue(0);
  }
}

var shapeLayout = new ui.VLayout();
shapeLayout.addSeparator("Dither shape");
var shapeName = new ui.LineEdit();
shapeName.setPlaceholder("Shape name");
var shapeNameRow = new ui.HLayout();
shapeNameRow.add(new ui.Label("Name"), shapeName);
var bakeShapeButton = new ui.Button("Bake dither shape");
bakeShapeButton.onClick = function () {
  bakeShape();
};
shapeLayout.add(
  shapeNameRow,
  new ui.Label("Uses the parameter list above (none linked = one static state)."),
  bakeShapeButton
);

rebuildBindings();
tessellationLayout.add(
  nameRow,
  presetRow,
  customRow,
  addBinding,
  bindingScroll,
  bakeTessellation,
  bakeProgress
);

ui.add(row);
ui.add(createA3);
ui.add(status);
ui.add(tessellationLayout);
ui.add(shapeLayout);
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
      status.setText("Waiting — choose in PlotterForge (continue or new layer)");
    } else {
      status.setText("Server error " + client.status());
    }
  } catch (e) {
    // Server down or render failed: show once, stay quiet until next change.
    status.setText("Plotter app offline (start-windows.bat)");
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
