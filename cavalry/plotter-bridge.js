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
