# Proposed physical marking workflow

No electronics wiring or machine interface is implemented in this repository. The software produces a QR SVG and stores asset/inspection records. It does not engrave, direct a laser, operate railway infrastructure or issue repair-control commands.

## Bench demonstration

Use a computer, ordinary printer or screen, an external QR reader, and a mock component/card. Register a synthetic ID, generate a QR, display/print it with a white background and preserved four-module quiet zone, then scan and paste the payload into the CLI. Record print/display size, lighting, angle, distance and reader for test results.

## Laser/direct-marking extension (proposed)

Before physical marking, define the actual component and approved marking area, identify applicable owner requirements, evaluate material/surface effects and obtain the required engineering authorization. Mark dimensions, contrast, distortion, wear, corrosion and reader compatibility need separate validation. QR vs DataMatrix and a suitable issued asset identifier should be chosen against actual requirements rather than assumed interchangeable.

The SVG is not a laser toolpath and contains no calibrated dimensions for a particular material. Do not load it into machinery as a ready production job. Machine selection, enclosure/interlocks, process parameters and structural/material validation are outside this package. No physical asset was marked during repository creation.

## Equipment not yet specified

Laser system, camera/reader, label material, component material, controller, marking location, environmental protection and power supply remain undecided. Do not invent a bill of materials or pin diagram until these are known. A software architecture diagram replaces an irrelevant MCU wiring diagram for this reference workflow.
