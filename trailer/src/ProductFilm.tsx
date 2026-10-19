import React from "react";
import {
  AbsoluteFill,
  CanvasImage,
  Interactive,
  Track,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Audio, Video } from "@remotion/media";
import { exercise, assessment } from "./evidence";

const navy = "#19323d",
  teal = "#277d86",
  amber = "#a96713",
  muted = "#61727a",
  paper = "#f3f6f7";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const time = (s: number) =>
  [Math.floor(s / 3600), Math.floor((s % 3600) / 60), Math.floor(s % 60)]
    .map((v) => String(v).padStart(2, "0"))
    .join(":");
const enter = (frame: number, delay = 0) =>
  interpolate(frame, [delay, delay + 18], [0, 1], clamp);

const Page: React.FC<{
  children: React.ReactNode;
  chapter: string;
  step: number;
  dark?: boolean;
  context?: string;
}> = ({
  children,
  chapter,
  step,
  dark = false,
  context = "Irish Sea exercise / fictional vessel / simulated observations",
}) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        fontFamily: "Segoe UI, Arial, sans-serif",
        background: dark ? navy : paper,
        color: dark ? "white" : navy,
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 70,
          right: 70,
          top: 38,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 23,
        }}
      >
        <strong style={{ fontSize: 26 }}>ARGUS MARA</strong>
        <span style={{ color: dark ? "#b9cdd4" : muted }}>{context}</span>
      </div>
      <div
        style={{
          position: "absolute",
          left: 70,
          right: 70,
          top: 92,
          height: 1,
          background: dark ? "#42616e" : "#ced8dc",
        }}
      />
      <AbsoluteFill
        style={{
          opacity: enter(f),
          translate: `0 ${interpolate(f, [0, 18], [18, 0], clamp)}px`,
        }}
      >
        {children}
      </AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 70,
          bottom: 33,
          fontSize: 22,
          color: dark ? "#b9cdd4" : muted,
        }}
      >
        {chapter}
      </div>
      <div
        style={{
          position: "absolute",
          right: 70,
          bottom: 33,
          fontSize: 22,
          color: dark ? "#b9cdd4" : muted,
        }}
      >
        {step} / 8
      </div>
    </AbsoluteFill>
  );
};
const Title: React.FC<{
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ children, style }) => (
  <div
    style={{
      position: "absolute",
      left: 70,
      top: 125,
      right: 70,
      fontSize: 64,
      lineHeight: 1.12,
      fontWeight: 600,
      letterSpacing: -1.5,
      ...style,
    }}
  >
    {children}
  </div>
);
const Note: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      position: "absolute",
      left: 70,
      right: 70,
      bottom: 86,
      fontSize: 25,
      lineHeight: 1.4,
      color: muted,
    }}
  >
    {children}
  </div>
);
const Screen: React.FC<{
  clip: "replay" | "review";
  trim?: number;
  rate?: number;
  style?: React.CSSProperties;
  zoom?: number;
}> = ({ clip, trim = 0, rate = 1, style, zoom = 1 }) => {
  const { fps } = useVideoConfig();
  const f = useCurrentFrame();
  return (
    <div
      style={{
        position: "absolute",
        left: 70,
        top: 250,
        width: 1240,
        height: 698,
        overflow: "hidden",
        background: "white",
        border: "1px solid #cbd6da",
        ...style,
      }}
    >
      <Video
        muted
        objectFit="cover"
        src={staticFile(`recordings/${clip}.mp4`)}
        trimBefore={trim * fps}
        playbackRate={rate}
        style={{
          width: "100%",
          height: "100%",
          scale: interpolate(f, [0, 240], [zoom, zoom + 0.035], clamp),
        }}
      />
    </div>
  );
};
const Point: React.FC<{
  children: React.ReactNode;
  delay: number;
  style?: React.CSSProperties;
}> = ({ children, delay, style }) => {
  const f = useCurrentFrame();
  return (
    <div
      style={{
        opacity: enter(f, delay),
        translate: `${(1 - enter(f, delay)) * 22}px 0`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Opening = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Page
        chapter="What the tool does"
        step={1}
        dark
        context="Native workspace capture / source labels retained"
      >
        <Title style={{ width: 750, top: 210, fontSize: 76 }}>
          Review maritime activity near undersea infrastructure.
        </Title>
        <div
          style={{
            position: "absolute",
            left: 75,
            top: 590,
            width: 660,
            fontSize: 31,
            lineHeight: 1.5,
            color: "#c2d4db",
          }}
        >
          Bring observations together, estimate the crossing window, and compare
          response timing.
        </div>
        <div
          style={{
            position: "absolute",
            left: 870,
            top: 160,
            width: 980,
            height: 695,
            overflow: "hidden",
            boxShadow: "0 20px 45px #0004",
          }}
        >
          <CanvasImage
            src={staticFile("native-workspace.png")}
            style={{
              width: "100%",
              height: "100%",
              objectPosition: "58% center",
              scale: interpolate(f, [0, 210], [1.05, 1.16], clamp),
            }}
          />
        </div>
        <div
          style={{
            position: "absolute",
            left: 870,
            top: 878,
            fontSize: 21,
            color: "#b9cdd4",
          }}
        >
          Existing native workspace capture. The replay below is a separate
          exercise.
        </div>
      </Page>
    );
  },
});

export const Reveal = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Page chapter="1. Replay the received observations" step={2}>
        <Title>Follow the track. Keep reception gaps visible.</Title>
        <Screen clip="replay" trim={2} style={{ width: 1250, height: 703 }} />
        <div style={{ position: "absolute", left: 1390, top: 282, width: 420 }}>
          <Point delay={10}>
            <div style={{ fontSize: 26, color: muted }}>Fictional tanker</div>
            <div style={{ fontSize: 39, fontWeight: 600, marginTop: 9 }}>
              CORMORANT STAR
            </div>
          </Point>
          <Point delay={50} style={{ marginTop: 62 }}>
            <div style={{ fontSize: 56, color: teal }}>12.0 kn</div>
            <div style={{ fontSize: 28, marginTop: 8 }}>
              Initial passage speed
            </div>
          </Point>
          <Point delay={100} style={{ marginTop: 55 }}>
            <div style={{ fontSize: 30, lineHeight: 1.45 }}>
              The replay preserves what was received. Missing AIS positions stay
              missing.
            </div>
          </Point>
          <div style={{ height: 5, background: "#d9e3e6", marginTop: 40 }}>
            <div
              style={{
                height: 5,
                background: teal,
                width: `${interpolate(f, [0, 240], [0, 100], clamp)}%`,
              }}
            />
          </div>
        </div>
      </Page>
    );
  },
});

const fixes = exercise.vessels[0].track.filter((p) => p.t <= 5400);
const SpeedPlot = () => {
  const f = useCurrentFrame();
  const p = enter(f, 185);
  const x = (t: number) => 85 + (t / 5400) * 930;
  const y = (v: number) => 290 - (v - 8) * 52;
  let path = "";
  fixes.forEach((v, i) => {
    path += `${i === 0 || v.t - fixes[i - 1].t > 120 ? "M" : "L"}${x(v.t)} ${y(v.sog_kn)} `;
  });
  return (
    <svg viewBox="0 0 1100 390" width="100%" height="100%">
      <defs>
        <clipPath id="speedReveal">
          <rect
            width={1100 * interpolate(f, [0, 200], [0, 1], clamp)}
            height="390"
          />
        </clipPath>
      </defs>
      {[9, 10, 11, 12].map((v) => (
        <g key={v}>
          <line x1="85" x2="1020" y1={y(v)} y2={y(v)} stroke="#d5dfe3" />
          <text x="28" y={y(v) + 7} fill={muted} fontSize="22">
            {v}
          </text>
        </g>
      ))}
      <rect
        x={x(1800)}
        y="50"
        width={x(3000) - x(1800)}
        height="245"
        fill="#e9c787"
        opacity=".38"
      />
      <text x={x(1800) + 15} y="82" fontSize="22" fill={amber}>
        20-minute gap
      </text>
      <path
        d={path}
        fill="none"
        stroke={teal}
        strokeWidth="5"
        clipPath="url(#speedReveal)"
      />
      {[
        [0, "08:00"],
        [1800, "08:30"],
        [3000, "08:50"],
        [5400, "09:30"],
      ].map(([t, l]) => (
        <text
          key={String(l)}
          x={x(Number(t))}
          y="340"
          textAnchor="middle"
          fill={muted}
          fontSize="23"
        >
          {l}
        </text>
      ))}
      <text x="82" y="27" fill={muted} fontSize="23">
        Speed / knots
      </text>
      <circle cx={x(5400)} cy={y(9.1)} r={p * 7} fill={teal} />
      <text x="1030" y={y(9.1) + 9} fill={teal} fontSize="27">
        9.1
      </text>
    </svg>
  );
};

export const Signals = Interactive.create({
  layout: "absolute-fill",
  Component: () => (
    <Page chapter="2. Explain why the alert appeared" step={3}>
      <Title>Four documented cues. Each open to review.</Title>
      <div
        style={{
          position: "absolute",
          left: 70,
          top: 295,
          width: 1100,
          height: 390,
        }}
      >
        <SpeedPlot />
      </div>
      <div style={{ position: "absolute", left: 1230, top: 285, width: 600 }}>
        {[
          ["24% slowdown", "12.0 kn to 9.1 kn"],
          ["30° course change", "Compared with the pre-gap fix"],
          ["20-minute reception gap", "08:30 to 08:50 UTC"],
          ["Projected cable crossing", "Using the alert fix at 09:30 UTC"],
        ].map(([title, detail], i) => (
          <Point
            key={title}
            delay={i * 45}
            style={{ padding: "17px 0", borderBottom: "1px solid #ccd8dd" }}
          >
            <div style={{ fontSize: 31, fontWeight: 600 }}>{title}</div>
            <div style={{ fontSize: 25, color: muted, marginTop: 7 }}>
              {detail}
            </div>
          </Point>
        ))}
      </div>
      <div
        style={{
          position: "absolute",
          left: 100,
          top: 735,
          fontSize: 29,
          width: 1000,
          lineHeight: 1.45,
        }}
      >
        The shaded interval contains no AIS fixes.
        <br />
        The chart does not invent a continuous track through it.
      </div>
      <Note>
        “4 of 4 cues” describes rule completeness. It is not a probability of
        hostile intent. Causes remain unknown.
      </Note>
    </Page>
  ),
});

export const Approach = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Page chapter="3. Inspect the separate radar observation" step={4}>
        <Title>A radar contact adds a question for the analyst.</Title>
        <div
          style={{
            position: "absolute",
            left: 70,
            top: 250,
            width: 1100,
            height: 619,
            overflow: "hidden",
            border: "1px solid #cbd6da",
            background: "white",
          }}
        >
          <CanvasImage
            src={staticFile("review.png")}
            style={{
              position: "absolute",
              width: 2460,
              height: 1384,
              left: -720,
              top: -370 + interpolate(f, [0, 330], [0, -30], clamp),
            }}
          />
          <div
            style={{
              position: "absolute",
              left: 70,
              top: 195,
              width: 930,
              height: 155,
              borderLeft: "4px solid #277d86",
              opacity: enter(f, 40),
              pointerEvents: "none",
            }}
          />
        </div>
        <div style={{ position: "absolute", left: 1240, top: 280, width: 600 }}>
          <div style={{ fontSize: 25, color: muted }}>
            Radar length estimate / simulated
          </div>
          <div style={{ fontSize: 67, color: teal, marginTop: 10 }}>228 m</div>
          <div
            style={{
              height: 12,
              marginTop: 15,
              background: teal,
              width: interpolate(f, [0, 65], [0, 500], clamp),
            }}
          />
          <div style={{ fontSize: 25, color: muted, marginTop: 45 }}>
            AIS-declared vessel length / fictional
          </div>
          <div style={{ fontSize: 67, marginTop: 10 }}>180 m</div>
          <div
            style={{
              height: 12,
              marginTop: 15,
              background: "#71818a",
              width: interpolate(f, [30, 95], [0, (500 * 180) / 228], clamp),
            }}
          />
          <Point
            delay={100}
            style={{
              marginTop: 50,
              fontSize: 32,
              lineHeight: 1.4,
              color: amber,
            }}
          >
            Association and identity remain unconfirmed.
          </Point>
        </div>
        <Note>
          The radar contact is a separate simulated observation. Measurement
          uncertainty and vessel identity require review.
        </Note>
      </Page>
    );
  },
});

const Projection = () => {
  const f = useCurrentFrame();
  const fix = fixes[fixes.length - 1];
  const cable = exercise.cables[0].path;
  const x = (lon: number) => 90 + ((lon + 6.12) / 1.5) * 970;
  const y = (lat: number) => 610 - ((lat - 52.85) / 0.6) * 520;
  const angle = (fix.cog_deg * Math.PI) / 180;
  const dx = Math.sin(angle) / Math.cos((fix.lat * Math.PI) / 180),
    dy = Math.cos(angle);
  let end = [fix.lon, 53.36];
  let nearest = Infinity;
  for (let i = 1; i < cable.length; i++) {
    const a = cable[i - 1],
      b = cable[i],
      sx = b[1] - a[1],
      sy = b[0] - a[0],
      det = dx * sy - dy * sx;
    if (!det) continue;
    const qx = a[1] - fix.lon,
      qy = a[0] - fix.lat;
    const t = (qx * sy - qy * sx) / det,
      u = (qx * dy - qy * dx) / det;
    if (t > 0 && u >= 0 && u <= 1 && t < nearest) {
      nearest = t;
      end = [fix.lon + t * dx, fix.lat + t * dy];
    }
  }
  const grow = interpolate(f, [20, 210], [0, 1], clamp);
  return (
    <svg viewBox="0 0 1150 730" width="100%" height="100%">
      <rect width="1150" height="730" fill="#e9f0f3" />
      {[52.9, 53.1, 53.3].map((lat) => (
        <g key={lat}>
          <line x1="85" x2="1080" y1={y(lat)} y2={y(lat)} stroke="#c9d7dd" />
          <text x="8" y={y(lat) + 8} fontSize="19" fill={muted}>
            {lat.toFixed(1)}°N
          </text>
        </g>
      ))}
      <path
        d={cable
          .map((p, i) => `${i ? "L" : "M"}${x(p[1])} ${y(p[0])}`)
          .join(" ")}
        fill="none"
        stroke={navy}
        strokeWidth="5"
      />
      <text x="120" y={y(53.36) - 25} fill={navy} fontSize="25">
        Illustrative Dublin–Holyhead cable route
      </text>
      <path
        d={fixes
          .map(
            (p, i) =>
              `${i === 0 || p.t - fixes[i - 1].t > 120 ? "M" : "L"}${x(p.lon)} ${y(p.lat)}`,
          )
          .join(" ")}
        fill="none"
        stroke={teal}
        strokeWidth="4"
      />
      <line
        x1={x(fix.lon)}
        y1={y(fix.lat)}
        x2={x(fix.lon + (end[0] - fix.lon) * grow)}
        y2={y(fix.lat + (end[1] - fix.lat) * grow)}
        stroke={amber}
        strokeWidth="4"
        strokeDasharray="9 7"
      />
      <circle cx={x(fix.lon)} cy={y(fix.lat)} r="8" fill={teal} />
      <text x={x(fix.lon) + 22} y={y(fix.lat) + 14} fontSize="24" fill={navy}>
        Alert fix / 09:30 UTC
      </text>
      <circle
        cx={x(end[0])}
        cy={y(end[1])}
        r="13"
        fill="white"
        stroke={amber}
        strokeWidth="4"
        opacity={enter(f, 170)}
      />
      <text x="120" y="682" fill={muted} fontSize="22">
        Solid: received AIS fixes Dashed: constant-course projection
      </text>
    </svg>
  );
};

export const Countdown = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Page chapter="4. Estimate the available review window" step={5}>
        <Title>Project the current course toward the cable.</Title>
        <div
          style={{
            position: "absolute",
            left: 70,
            top: 240,
            width: 1110,
            height: 700,
          }}
        >
          <Projection />
        </div>
        <div style={{ position: "absolute", left: 1250, top: 270, width: 580 }}>
          <div style={{ fontSize: 25, color: muted }}>
            Expected crossing from the alert fix
          </div>
          <div
            style={{
              fontSize: 94,
              fontVariantNumeric: "tabular-nums",
              letterSpacing: -3,
              color: navy,
              marginTop: 12,
              opacity: enter(f, 15),
            }}
          >
            {time(assessment.eta_expected_s)}
          </div>
          <div style={{ fontSize: 26, color: muted, marginTop: 42 }}>
            Earliest planning estimate
          </div>
          <div style={{ fontSize: 61, color: amber, marginTop: 10 }}>
            {time(assessment.eta_earliest_s)}
          </div>
          <Point
            delay={95}
            style={{ fontSize: 28, lineHeight: 1.5, marginTop: 45 }}
          >
            9.1 kn speed and 350.3° course.
            <br />
            Earliest estimate uses 20% higher speed.
          </Point>
          <Point
            delay={170}
            style={{
              fontSize: 25,
              lineHeight: 1.4,
              marginTop: 30,
              color: muted,
            }}
          >
            These are planning projections,
            <br />
            not calibrated confidence bounds.
          </Point>
        </div>
      </Page>
    );
  },
});

export const Options = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const x = (m: number) => 530 + (m / 260) * 1260;
    const cutoff = assessment.eta_earliest_s / 60;
    return (
      <Page chapter="5. Compare response arrival times" step={6}>
        <Title>Which options arrive before the earliest estimate?</Title>
        <svg
          width="1920"
          height="1080"
          style={{ position: "absolute", inset: 0 }}
        >
          {[0, 60, 120, 180, 240].map((m) => (
            <g key={m}>
              <line x1={x(m)} x2={x(m)} y1="290" y2="850" stroke="#d6e0e4" />
              <text
                x={x(m)}
                y="895"
                textAnchor="middle"
                fill={muted}
                fontSize="25"
              >
                {m} min
              </text>
            </g>
          ))}
          <line
            x1={x(cutoff)}
            x2={x(cutoff)}
            y1="300"
            y2="850"
            stroke={amber}
            strokeWidth="3"
            strokeDasharray="7 7"
          />
          <text x={x(cutoff) + 12} y="268" fill={amber} fontSize="25">
            Earliest crossing / 61 min 15 s
          </text>
          {[
            assessment.options[2],
            assessment.options[0],
            assessment.options[1],
            assessment.options[3],
          ].map((o, i) => {
            const minutes = o.eta_s / 60;
            const len = (x(minutes) - x(0)) * enter(f, i * 22 + 8);
            const y = 360 + i * 135;
            const names = [
              "VHF hail",
              "Patrol aircraft",
              "Patrol ship",
              "Next satellite look",
            ];
            return (
              <g key={o.asset}>
                <text x="75" y={y + 8} fontSize="31" fill={navy}>
                  {names[i]}
                </text>
                <line
                  x1={x(0)}
                  x2={x(0) + len}
                  y1={y}
                  y2={y}
                  stroke={o.in_time ? teal : "#83929a"}
                  strokeWidth="15"
                />
                <circle
                  cx={x(0) + len}
                  cy={y}
                  r="10"
                  fill={o.in_time ? teal : "#83929a"}
                />
                <text
                  x={x(minutes) + 20}
                  y={y + 9}
                  fontSize="27"
                  fill={navy}
                  opacity={enter(f, i * 22 + 35)}
                >
                  {Math.round(minutes)} min
                </text>
                <text
                  x="75"
                  y={y + 43}
                  fontSize="23"
                  fill={o.in_time ? teal : muted}
                >
                  {o.in_time
                    ? "Arrives within the planning window"
                    : "Arrives after the planning window"}
                </text>
              </g>
            );
          })}
        </svg>
        <Note>
          All response capabilities and arrival times are assumptions. The
          comparison uses the earliest estimate, not the expected crossing time.
        </Note>
      </Page>
    );
  },
});

export const Decision = Interactive.create({
  layout: "absolute-fill",
  Component: () => (
    <Page chapter="6. Record a human decision" step={7}>
      <Title>Review the evidence. Approve an exercise response.</Title>
      <Screen
        clip="review"
        trim={5.2}
        style={{ left: 70, top: 250, width: 1295, height: 728 }}
      />
      <div style={{ position: "absolute", left: 1430, top: 310, width: 400 }}>
        <Point delay={10} style={{ fontSize: 34, lineHeight: 1.4 }}>
          1. Choose a simulated response.
        </Point>
        <Point
          delay={55}
          style={{ fontSize: 34, lineHeight: 1.4, marginTop: 60 }}
        >
          2. Confirm the evidence and uncertainty were reviewed.
        </Point>
        <Point
          delay={120}
          style={{ fontSize: 34, lineHeight: 1.4, marginTop: 60, color: teal }}
        >
          3. Record the decision.
        </Point>
      </div>
      <div
        style={{
          position: "absolute",
          left: 1430,
          top: 850,
          width: 400,
          fontSize: 23,
          lineHeight: 1.4,
          color: muted,
        }}
      >
        This is a local exercise decision.
        <br />
        No operational response is sent.
      </div>
    </Page>
  ),
});

export const Closing = Interactive.create({
  layout: "absolute-fill",
  Component: () => (
    <Page
      chapter="EUDIS Challenge 3 / Space-Enabled Maritime Domain Awareness"
      step={8}
      dark
    >
      <div
        style={{
          position: "absolute",
          left: 100,
          top: 220,
          fontSize: 110,
          fontWeight: 600,
        }}
      >
        ARGUS MARA
      </div>
      <div
        style={{
          position: "absolute",
          left: 105,
          top: 420,
          width: 1500,
          fontSize: 54,
          lineHeight: 1.5,
        }}
      >
        Review the cues.
        <br />
        Compare the timing.
        <br />
        Keep an evidence record.
      </div>
      <div
        style={{
          position: "absolute",
          left: 105,
          top: 800,
          right: 100,
          fontSize: 29,
          color: "#c2d4db",
        }}
      >
        Offline replay. Explainable rules. Evidence labels. Human approval.
      </div>
    </Page>
  ),
});

export const Trailer = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Audio src={staticFile("soundtrack.wav")} volume={0.55} />
      <Track name="Product demonstration">
        <Opening durationInFrames={7 * fps} />
        <Reveal from={7 * fps} durationInFrames={8 * fps} />
        <Signals from={15 * fps} durationInFrames={12 * fps} />
        <Approach from={27 * fps} durationInFrames={11 * fps} />
        <Countdown from={38 * fps} durationInFrames={13 * fps} />
        <Options from={51 * fps} durationInFrames={11 * fps} />
        <Decision from={62 * fps} durationInFrames={8 * fps} />
        <Closing from={70 * fps} durationInFrames={5 * fps} />
      </Track>
    </AbsoluteFill>
  );
};
export const ShortTrailer = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Audio src={staticFile("short-soundtrack.wav")} volume={0.55} />
      <Track name="Short product demonstration">
        <Opening durationInFrames={4 * fps} />
        <Reveal from={4 * fps} durationInFrames={4 * fps} />
        <Signals from={8 * fps} durationInFrames={5 * fps} />
        <Countdown from={13 * fps} durationInFrames={7 * fps} />
        <Decision from={20 * fps} durationInFrames={5 * fps} />
        <Closing from={25 * fps} durationInFrames={5 * fps} />
      </Track>
    </AbsoluteFill>
  );
};
