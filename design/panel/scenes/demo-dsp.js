.pragma library

// Synthetic drawer data for the mock-ups (EQ, gate, compressor, voices, autotune). The app's
// core does not read any of it yet: there `sc3.dsp` is {} and every card whose key is missing
// shows «появится позже» instead of numbers. Shape (the contract for the Python side; every
// key is optional, a card appears as soon as its key is there):
//   Row   = { label: string, value: string (ready to show), fraction: 0..1 (bar end),
//             centre?: 0..1 (bar is bipolar around it) }               -> ParamRow.row
//   Value = { value: string (ready to show), fraction: 0..1 }
//   eq:       { on: bool, bands: [{ kind: "hp" | "ls" | "pk", f: Hz, q: real, g: dB,
//                                   name: string }], selected?: int (band being edited) }
//   gate:     { on: bool, level: Value (input now), threshold: 0..1 (on the level bar),
//               rows: [Row] }
//   comp:     { on: bool, threshold: dB, ratio: real, knee: dB, input: dB (now),
//               reduction: Value (gain reduction now), rows: [Row] }
//   gain:     { value: string, fraction: 0..1, centre: 0..1 (where 0 dB is),
//               ticks: [{ text: string, fraction: 0..1 }], peak: string (output peak now) }
//   voices:   { factory: { <as printed: "Male" | "Female" | "Robot" | "Monster" | "Baby" |
//                           "Elder">: { pitch: semitones, formant: semitones,
//                                       extra?: string (shown instead of the formant),
//                                       rows?: [Row] (more parameters of the selected voice) } },
//               own: [{ name: string, pitch: semitones, formant: semitones, extra?: string }] }
//   autotune: { scale: "major" | "minor" | "chromatic", speedMs: real (retune time),
//               speed: Value, rows: [Row] }
// The key and the voice themselves are not here: they are sc3.electricKey and sc3.voice.

var voiceRows = [
    { label: "Смесь с исходным", value: "100 %", fraction: 1 },
    { label: "Громкость голоса", value: "+1,0 дБ", fraction: 13 / 24, centre: 0.5 }
]

var dsp = ({
    eq: {
        on: true,
        selected: 3,
        bands: [
            { kind: "hp", f: 80, q: 0.707, g: 0, name: "срез" },
            { kind: "ls", f: 160, q: 0.707, g: 2.0, name: "полка" },
            { kind: "pk", f: 450, q: 1.4, g: -2.5, name: "пик" },
            { kind: "pk", f: 4000, q: 1.0, g: 3.5, name: "пик" },
            { kind: "pk", f: 7500, q: 3.0, g: -2.0, name: "пик" }
        ]
    },
    gate: {   // bar: -80..0 dBFS
        on: true,
        level: { value: "−24 дБ", fraction: (80 - 24) / 80 },
        threshold: (80 - 52) / 80,
        rows: [
            { label: "Порог", value: "−52 дБ", fraction: 28 / 80 },
            { label: "Атака", value: "2 мс", fraction: 2 / 50 },
            { label: "Отпуск", value: "180 мс", fraction: 0.18 },
            { label: "Глубина", value: "−30 дБ", fraction: 0.5 }
        ]
    },
    comp: {
        on: true,
        threshold: -18,
        ratio: 3,
        knee: 6,
        input: -12,
        reduction: { value: "−3,2 дБ", fraction: 3.2 / 12 },   // bar: 0..-12 dB
        rows: [
            { label: "Порог", value: "−18 дБ", fraction: 42 / 60 },
            { label: "Степень", value: "3 : 1", fraction: 2 / 9 },
            { label: "Атака", value: "8 мс", fraction: 8 / 100 },
            { label: "Отпуск", value: "120 мс", fraction: 0.12 },
            { label: "Подъём", value: "+4 дБ", fraction: 4 / 24 },
            { label: "Колено", value: "6 дБ", fraction: 6 / 24 }
        ]
    },
    gain: {   // bar: -12..+24 dB
        value: "+6,0 дБ",
        fraction: 18 / 36,
        centre: 12 / 36,
        ticks: [
            { text: "−12", fraction: 0 },
            { text: "0", fraction: 12 / 36 },
            { text: "+24", fraction: 1 }
        ],
        peak: "−6,1 дБFS"
    },
    voices: {
        factory: {
            Male: { pitch: -5, formant: -2, rows: voiceRows },
            Female: { pitch: 5, formant: 4.5, rows: voiceRows },
            Robot: { pitch: 0, formant: 0, extra: "модуляция", rows: voiceRows },
            Monster: { pitch: -9, formant: -5, rows: voiceRows },
            Baby: { pitch: 9, formant: 6.5, rows: voiceRows },
            Elder: { pitch: -3, formant: 2.5, extra: "дрожание", rows: voiceRows }
        },
        own: [
            { name: "Диктор", pitch: -2, formant: -6.5 },
            { name: "Рация", pitch: 4, formant: -3, extra: "полоса 300–3000 Гц" }
        ]
    },
    autotune: {
        scale: "major",
        speedMs: 20,
        speed: { value: "20 мс", fraction: 0.1 },   // bar: robot (0 ms) .. natural (200 ms)
        rows: [
            { label: "Сила", value: "100 %", fraction: 1 }
        ]
    }
})
