# IC Manager, Review Responses

Responses to *"First review of the IC manager"*. Status legend: ✅ done · 🔧 in progress · 🟡 needs decision · 📋 planned.

| # | Change request | Answer / Status |
|---|----------------|-----------------|
| 1 | Pressing Enter in the edit dialog triggers "Manage projects" instead of saving | ✅ **Done.** Enter now saves & closes the dialog. (The "Manage projects" button was grabbing the Enter key.) |
| 2 | "Add project" Description box should be able to grow | ✅ **Done.** Replaced the single-line box with a multi-line, resizable text box. |
| 3 | Can't see the rows below while typing in the Comments section | ✅ **Done.** Comments is now a multi-line, growable box; Tab moves to the next field. |
| 4 | "In repair" brackets should turn red instead of grey | ✅ **Done.** In-repair bars now render red regardless of project, and the "In repair" status pill is a clearer red. |
| 5 | Clock: clicking the time lands on the un-editable `:00`, hours hard to edit | ✅ **Done.** Clicking or focusing the time now snaps to the hour section, so typing and the arrows work immediately. Kept hours-only (no minutes). |
| 6 | Can't see the year when changing the year | ✅ **Done.** The year editor in the calendar popup now has a solid white field with dark text, so the year is clearly visible while changing it. |
| 7 | Clock: can only edit the date with the calendar icon | 🟡 By design (date is picked from the calendar to avoid typos). Reviewing alongside items 9/10; open to allowing typed dates if preferred. |
| 8 | Bar label should sit at the right end of the bracket, not the left | ✅ **Done.** All bars in the Station Summary now right-align their label. |
| 9 | Periodic bug: hours can't be edited (typing or arrows), seen while cell was Available | 🟡 Investigating; likely tied to the locked/disabled state when Available. |
| 10 | Can't change Separator / Added water when status is "Available" (clock can't be removed) | ✅ **Done.** A safety check was refusing to save an Available cell that "still had data," but it counted the always-present date/hour as data and blocked every save. It now only triggers on genuinely typed data, so Separator and Added water can be edited freely. |
| 11 | Station summary says "in repair 15" when only 6 are in repair | ✅ **Done.** The footer counts now come from each channel's current status in the live cells table (the source of truth), instead of the latest history episode, which lingered on "In repair" after a channel had already moved on. |
| 12 | Brackets grow off-screen in the wrong direction when updated on another PC | ✅ **Done.** Not a data problem (a restart always looked correct), it was a re-render bug: a live update rebuilt the chart, and rebuilding moved the scrollbar, which recursively re-triggered the chart rebuild mid-render and corrupted the bar lengths. Added a guard so a rebuild can't re-enter itself. |
| 13 | Colour & name for available channels in the station summary | 📋 Planned (feature). |
| 14 | Option to add a custom label on the station-summary brackets | 📋 Planned (feature; needs a new stored field). |
| 15 | Be able to change the ordering of the projects | 📋 Planned (feature; needs a persisted order). |
| 16 | Add expected end date / run-time to experiments | 📋 Planned (feature; new field + bar rendering). |
| 17 | Zoom in / out in Cells Mapping and Station Summary | ✅ **Done.** Both tabs have a shared − / % / + zoom control in the toolbar that scales the row height and font size (10% steps, 70–200%). In the Station Summary the day-column width stays fixed and zooming keeps the current scroll position. |
| 18 | Automated filename generation (`ICXXXX_CatX_AnoX_rhoXXXX_X.Xppm_Fe_XX`) | 📋 Planned (largest item; needs density/Fe data, auto IC number, confirm popup, own design session). |
