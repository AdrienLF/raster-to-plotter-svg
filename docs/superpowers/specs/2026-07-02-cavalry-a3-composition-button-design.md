# Cavalry A3 Composition Button

## Goal

Add a button to the Cavalry Plotter Bridge that creates a portrait A3 composition at the app's working scale of 10 pixels per millimetre.

## Behaviour

- The bridge window shows a **New A3 Composition** button.
- Clicking it creates a new Cavalry composition named `A3 Plotter · 10 px/mm`.
- The composition resolution is `2970 × 4200` pixels, corresponding to `297 × 420 mm` at 10 px/mm.
- The new composition becomes the active composition.
- Existing compositions are never resized or otherwise modified.
- Activating the composition triggers the bridge's existing debounced capture flow.
- If Cavalry cannot create or configure the composition, the bridge displays a concise error status and logs the underlying error to the JavaScript Console.

## Implementation

Use Cavalry's documented scripting APIs:

1. `api.createComp(name)` to create the composition.
2. `api.set(compId, { resolution: [2970, 4200] })` to set its resolution.
3. `api.setActiveComp(compId)` to activate it.

The button is added through the existing script UI and does not require a new PlotterForge endpoint.

## Verification

- A script contract test verifies the button label, fixed dimensions, composition creation, resolution assignment, and activation calls.
- The Cavalry script passes JavaScript syntax validation.
- The full Python test suite remains green.
- The repository script is copied to the installed Cavalry Scripts folder and both copies are verified byte-identical.
