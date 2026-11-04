# FC26 Youth Tournament Probe v0.1

This is a temporary read-only diagnostic for discovering which
`CareerModeEvent` callbacks fire around a youth 5x5 match. It records each
event's phase, numeric ID, Live Editor event name and local timestamp in the
Live Editor log. It deliberately does not inspect event payloads or read/write
career tables, game memory, or the save.

## Controlled capture

1. Copy `FC26_YouthTournamentProbe_v0.1.lua` into the Live Editor `lua/scripts`
   folder. The current local copy is already staged there.
2. After the Live Editor overlay is confirmed visible, load the career and run
   the probe before starting a youth 5x5 tournament match.
3. Play one controlled youth 5x5 match, return to the Career Hub, and preserve
   the Live Editor log lines containing `[YOUTH_PROBE]` with the match date and
   observed result as separate notes.
4. Compare those events with a before/after career snapshot. Do not interpret
   the raw `gmty` scalar values as goals; the FC26 reverse-engineering notes
   falsify that interpretation.

This probe only establishes event timing. It does not export tournament
results, player performances, score, or opponent data. Those fields should be
added only after a controlled observation maps them to a real source.
