# What is in each scenario

Generated from `ui/viewer/scenarios.js` (the seeder output) by a small script; do not edit by hand. Use it to check the viewer against the truth: turn on the "truth" layer and compare. Coordinates are metres in the 1000 x 1000 m area; "enters" is the first waypoint, "leaves" the last.

The same five friendly drones (F1-F5) and two ground sensors (GS1, GS2) are in every scenario; the sensors differ only in `busy` (GS1 has a radar and an RF receiver instead of a camera and a microphone array).

## busy (seed 3, 120 s)

Mixed traffic: benign transit, survey orbit and hover, plus simulated pursuit and intercept behavior toward moving allies. Assessment uses observed encounters, without protected zones.

Weather clear, 1 radar false alarms per minute, 0 birds, 0 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 7.3 | 48 | transmits | (185,687) at 3 s | (1004,154) at 137 s |
| H2 | hostile | crossing | 11.6 | 56 | transmits | (987,710) at 8 s | (-4,224) at 103 s |
| H3 | hostile | loiter | 12.8 | 77 | transmits | (995,425) at 3 s | (5,395) at 110 s |
| H4 | hostile | hover | 10.9 | 64 | transmits | (5,395) at 11 s | (995,395) at 150 s |
| N1 | benign | straight | 10.6 | 42 | transmits | (20,720) at 4 s | (980,720) at 94 s |
| N2 | benign | straight | 7.8 | 109 | transmits | (980,600) at 10 s | (20,600) at 134 s |
| N3 | benign | loiter | 10.7 | 38 | transmits | (430,995) at 7 s | (430,995) at 126 s |
| N4 | benign | hover | 13.0 | 48 | transmits | (5,610) at 18 s | (5,610) at 103 s |

## challenge (seed 4127, 120 s)

The task scenario: five drones, two ground sensors, two hostiles crossing at close range, about 1 km2.

Weather clear, 3 radar false alarms per minute, 0 birds, 0 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 10.0 | 45 | transmits | (177,824) at 3 s | (903,-4) at 113 s |
| H2 | hostile | crossing | 13.7 | 44 | transmits | (914,976) at 3 s | (76,-4) at 97 s |

## dusk (seed 5, 120 s)

Four hostiles while the sun sets (one simulated minute per second, so the run goes from daylight to near night), a fog patch over the middle of the map for part of the run, birds and a vehicle.

Weather clear, 3 radar false alarms per minute, 2 birds, 1 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 8.4 | 108 | transmits | (82,680) at 3 s | (1004,203) at 127 s |
| H2 | hostile | crossing | 10.4 | 102 | transmits | (788,834) at 3 s | (-3,29) at 112 s |
| H3 | hostile | hover | 9.7 | 73 | transmits | (686,985) at 6 s | (1004,942) at 110 s |
| H4 | hostile | hover | 11.2 | 74 | transmits | (229,985) at 10 s | (490,1005) at 103 s |
| B1 | bird | waypoints | 12.1 | 32 | silent | (866,15) at 3 s | (-5,531) at 156 s |
| B2 | bird | waypoints | 10.7 | 18 | silent | (15,117) at 67 s | (834,1005) at 216 s |
| V1 | vehicle | straight | 4.3 | 1 | silent | (15,358) at 41 s | (-5,281) at 267 s |

## easy (seed 1, 120 s)

One hostile, five drones, two ground sensors, clean data.

Weather clear, 3 radar false alarms per minute, 0 birds, 0 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | straight | 12.0 | 46 | transmits | (985,724) at 7 s | (1004,211) at 85 s |

## hard (seed 3, 120 s)

Five hostiles with close crossings and hovering, fog, 40 % bursty loss, clock drift, pose error and a node dropout.

Weather fog, 6 radar false alarms per minute, 0 birds, 0 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 6.6 | 53 | transmits | (235,654) at 3 s | (1004,154) at 141 s |
| H2 | hostile | crossing | 16.7 | 56 | transmits | (987,710) at 18 s | (-4,224) at 84 s |
| H3 | hostile | hover | 19.5 | 62 | transmits | (603,15) at 15 s | (-4,819) at 89 s |
| H4 | hostile | hover | 16.2 | 41 | transmits | (876,15) at 11 s | (984,-4) at 102 s |
| H5 | hostile | hover | 12.4 | 45 | transmits | (985,880) at 18 s | (1004,236) at 118 s |

## jammed (seed 6, 120 s)

Three hostiles under electronic warfare: a strong jamming zone over the north-east that switches on at 30 s, a weaker permanent one in the west, and a 32 kbit/s link cap per node. Messages from nodes inside a zone are lost, and radio sensors there hear more noise.

Weather clear, 2 radar false alarms per minute, 0 birds, 1 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 10.2 | 40 | transmits | (37,724) at 3 s | (1005,290) at 107 s |
| H2 | hostile | crossing | 8.0 | 31 | transmits | (972,720) at 3 s | (-4,157) at 143 s |
| H3 | hostile | waypoints | 13.0 | 70 | transmits | (873,985) at 13 s | (-5,275) at 105 s |
| V1 | vehicle | straight | 9.1 | 1 | silent | (15,831) at 2 s | (495,-5) at 116 s |

## medium (seed 2, 120 s)

Three hostiles with one close crossing, moderate noise and loss.

Weather clear, 4 radar false alarms per minute, 0 birds, 0 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 12.7 | 60 | transmits | (14,766) at 4 s | (1005,388) at 87 s |
| H2 | hostile | crossing | 14.5 | 42 | transmits | (910,988) at 13 s | (181,-4) at 98 s |
| H3 | hostile | hover | 9.2 | 38 | transmits | (709,15) at 16 s | (1004,79) at 104 s |

## mixed (seed 8, 120 s)

One of every kind of object: 3 hostile drones (one crossing close, one hovering), 3 benign drones that transmit, 2 birds and 2 vehicles, with the five friendly drones and two ground sensors.

Weather clear, 2 radar false alarms per minute, 2 birds, 2 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 10.0 | 90 | transmits | (13,685) at 8 s | (1005,183) at 119 s |
| H2 | hostile | crossing | 12.4 | 117 | transmits | (977,825) at 3 s | (-4,207) at 97 s |
| H3 | hostile | loiter | 10.6 | 106 | transmits | (995,425) at 3 s | (5,395) at 132 s |
| N1 | benign | straight | 9.0 | 58 | transmits | (20,720) at 1 s | (980,720) at 107 s |
| N2 | benign | straight | 10.0 | 36 | transmits | (980,600) at 11 s | (20,600) at 107 s |
| N3 | benign | loiter | 11.9 | 68 | transmits | (430,995) at 4 s | (430,995) at 110 s |
| B1 | bird | waypoints | 7.1 | 26 | silent | (985,336) at 3 s | (715,1004) at 229 s |
| B2 | bird | waypoints | 8.0 | 37 | silent | (182,985) at 21 s | (503,1005) at 212 s |
| V1 | vehicle | straight | 9.2 | 1 | silent | (358,985) at 33 s | (878,1004) at 127 s |
| V2 | vehicle | straight | 6.2 | 1 | silent | (985,180) at 65 s | (-4,231) at 236 s |

## outage (seed 7, 120 s)

Three hostiles while nodes lose their link. F2's link is cut from 20 to 65 s (45 s: long enough to be called isolated), GS2's messages are delayed by 4 s from 70 to 85 s, and F4 goes down for good at 100 s. Store-and-forward is on: nodes keep what C2 has not acknowledged and resend it once the link is back. Faults apply in Realistic mode only.

Weather clear, 3 radar false alarms per minute, 0 birds, 0 vehicles.

| id | role | motion | speed m/s | altitude m | radio | enters | leaves |
|---|---|---|---|---|---|---|---|
| H1 | hostile | crossing | 8.4 | 81 | transmits | (38,799) at 3 s | (1004,222) at 137 s |
| H2 | hostile | crossing | 8.6 | 54 | transmits | (785,903) at 3 s | (-3,113) at 132 s |
| H3 | hostile | hover | 12.4 | 94 | transmits | (985,260) at 9 s | (1005,784) at 90 s |
