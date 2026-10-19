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
  delayRender,
  continueRender,
} from "remotion";
import { Audio, Video } from "@remotion/media";
import { loadFont } from "@remotion/fonts";
import { Chart, colors, clamp } from "./ChartFilm";
import { assessment } from "./evidence";

const fontHandle = delayRender("Loading film typography");
Promise.all([
  loadFont({
    family: "Barlow",
    url: staticFile("fonts/barlow-condensed-latin-700-normal.woff2"),
    weight: "700",
  }),
  loadFont({
    family: "DM Sans",
    url: staticFile("fonts/dm-sans-latin-400-normal.woff2"),
    weight: "400",
  }),
]).then(() => continueRender(fontHandle));
const show = (f: number, start = 0, duration = 18) =>
  interpolate(f, [start, start + duration], [0, 1], clamp);
const display = "Barlow, sans-serif",
  body = "DM Sans, sans-serif";
const clock = (s: number) =>
  [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60]
    .map((v) => String(v).padStart(2, "0"))
    .join(":");

const Film: React.FC<{
  children: React.ReactNode;
  context?: string;
  credit?: string;
}> = ({
  children,
  context = "Fictional exercise / simulated observations",
  credit = "Natural Earth coastline · public domain / illustrative cable geometry",
}) => (
  <AbsoluteFill
    style={{
      fontFamily: body,
      color: colors.white,
      background: colors.sea,
      overflow: "hidden",
    }}
  >
    {children}
    <div
      style={{
        position: "absolute",
        top: 0,
        height: 58,
        width: "100%",
        background: "#08131d",
      }}
    />
    <div
      style={{
        position: "absolute",
        bottom: 0,
        height: 63,
        width: "100%",
        background: "#08131d",
      }}
    />
    <div
      style={{
        position: "absolute",
        left: 62,
        top: 18,
        fontSize: 19,
        color: "#c6d3d5",
      }}
    >
      ARGUS MARA
    </div>
    <div
      style={{
        position: "absolute",
        right: 62,
        top: 18,
        fontSize: 18,
        color: "#94adb7",
      }}
    >
      {context}
    </div>
    <div
      style={{
        position: "absolute",
        left: 62,
        bottom: 23,
        fontSize: 17,
        color: "#90a7b0",
      }}
    >
      {credit}
    </div>
    <div
      style={{
        position: "absolute",
        right: 62,
        bottom: 23,
        fontSize: 17,
        color: "#d8c299",
      }}
    >
      Human review required
    </div>
  </AbsoluteFill>
);
const Text: React.FC<{
  children: React.ReactNode;
  x?: number;
  y?: number;
  size?: number;
  width?: number;
  style?: React.CSSProperties;
}> = ({ children, x = 95, y = 160, size = 110, width = 850, style }) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      width,
      fontFamily: display,
      fontWeight: 700,
      fontSize: size,
      lineHeight: 0.98,
      letterSpacing: -1,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Opening = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Film
        context="Existing native workspace capture"
        credit="Native application capture supplied with repository · source labels retained"
      >
        <CanvasImage
          src={staticFile("native-workspace.png")}
          style={{
            position: "absolute",
            width: 2100,
            height: 1320,
            left: interpolate(f, [0, 70, 210], [50, -50, -150], clamp),
            top: -100,
            objectFit: "cover",
            scale: interpolate(f, [0, 210], [1.15, 1], clamp),
          }}
        />
        <AbsoluteFill
          style={{
            background:
              "linear-gradient(90deg,#07131cf2 0%,#07131cd9 30%,#07131c30 70%)",
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 95,
            top: 155,
            width: 1050,
            clipPath: `inset(${(1 - show(f, 12, 25)) * 100}% 0 0 0)`,
          }}
        >
          <div
            style={{
              fontFamily: display,
              fontSize: 237,
              fontWeight: 700,
              lineHeight: 0.82,
              letterSpacing: -5,
            }}
          >
            ARGUS
            <br />
            MARA
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            left: 100,
            top: 650,
            width: 650,
            fontSize: 34,
            lineHeight: 1.35,
            opacity: show(f, 50),
          }}
        >
          Maritime awareness for
          <br />
          undersea infrastructure.
        </div>
        <div
          style={{
            position: "absolute",
            left: 100,
            top: 850,
            fontSize: 23,
            color: colors.gold,
            opacity: show(f, 95),
          }}
        >
          EUDIS Challenge 3 · Ireland
        </div>
      </Film>
    );
  },
});

export const Reveal = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const t = interpolate(f, [0, 240], [0, 1740], clamp);
    return (
      <Film>
        <Chart
          time={t}
          from={[60, 130, 1950, 1096.875]}
          to={[650, 530, 1000, 562.5]}
        />
        <AbsoluteFill
          style={{
            background: "linear-gradient(90deg,#07131cbf,transparent 60%)",
          }}
        />
        <Text y={170} size={122} width={720}>
          CORMORANT
          <br />
          STAR
        </Text>
        <div
          style={{
            position: "absolute",
            left: 100,
            top: 660,
            width: 550,
            fontSize: 28,
            lineHeight: 1.5,
            color: colors.muted,
          }}
        >
          Follow received AIS positions.
          <br />
          Keep reception gaps visible.
        </div>
        <div
          style={{
            position: "absolute",
            right: 95,
            bottom: 120,
            fontFamily: display,
            fontSize: 78,
          }}
        >
          12.0{" "}
          <span style={{ fontFamily: body, fontSize: 25, color: colors.muted }}>
            kn / initial passage
          </span>
        </div>
      </Film>
    );
  },
});

const TimeRail: React.FC<{ f: number }> = ({ f }) => {
  const p = interpolate(f, [0, 240], [1 / 3, 5 / 9], clamp);
  return (
    <div style={{ position: "absolute", left: 100, right: 100, bottom: 130 }}>
      <svg width="1720" height="140">
        <line x1="0" y1="80" x2="1720" y2="80" stroke="#627d8b" />
        <line
          x1="573.333"
          y1="80"
          x2="955.556"
          y2="80"
          stroke={colors.gold}
          strokeWidth="6"
        />
        <line
          x1="0"
          y1="80"
          x2={1720 * p}
          y2="80"
          stroke={colors.white}
          strokeWidth="2"
        />
        {[
          [0, "08:00"],
          [573.333, "08:30"],
          [955.556, "08:50"],
          [1720, "09:30"],
        ].map(([x, l]) => (
          <g key={String(l)}>
            <circle cx={Number(x)} cy="80" r="5" fill={colors.white} />
            <text
              x={Number(x)}
              y="125"
              fill={colors.muted}
              fontFamily={body}
              fontSize="22"
              textAnchor={x === 0 ? "start" : x === 1720 ? "end" : "middle"}
            >
              {l}
            </text>
          </g>
        ))}
        <text
          x="764.444"
          y="45"
          textAnchor="middle"
          fill={colors.gold}
          fontFamily={body}
          fontSize="25"
        >
          20-minute AIS reception gap
        </text>
      </svg>
    </div>
  );
};
export const Signals = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const t = interpolate(f, [0, 320], [1800, 3000], clamp);
    return (
      <Film>
        <Chart
          time={t}
          from={[700, 630, 800, 450]}
          to={[770, 635, 700, 393.75]}
        />
        <AbsoluteFill
          style={{
            background: "linear-gradient(90deg,#07131ccb,transparent 70%)",
          }}
        />
        <Text y={170} size={190} width={500}>
          20 MIN
        </Text>
        <div
          style={{
            position: "absolute",
            left: 105,
            top: 380,
            width: 620,
            fontSize: 36,
            lineHeight: 1.35,
          }}
        >
          AIS reception gap.
          <br />
          Cause unknown.
        </div>
        <div
          style={{
            position: "absolute",
            left: 105,
            top: 550,
            width: 540,
            fontSize: 26,
            lineHeight: 1.5,
            color: colors.muted,
            opacity: show(f, 70),
          }}
        >
          Missing positions stay missing.
          <br />A separate radar observation
          <br />
          arrives at 08:40 UTC.
        </div>
        <TimeRail f={f} />
      </Film>
    );
  },
});

export const Approach = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const t = interpolate(f, [0, 260], [3000, 5400], clamp);
    return (
      <Film>
        <Chart
          time={t}
          from={[730, 570, 900, 506.25]}
          to={[755, 550, 850, 478.125]}
        />
        <AbsoluteFill
          style={{
            background: "linear-gradient(90deg,#07131cdd,transparent 70%)",
          }}
        />
        <Text y={155} size={105} width={700}>
          AIS returns.
          <br />
          Course changes.
        </Text>
        <div style={{ position: "absolute", left: 105, top: 420, width: 650 }}>
          {[
            ["12.0 → 9.1 kn", "Observed slowdown"],
            ["30°", "Course change"],
            ["228 m / 180 m", "Radar estimate / AIS declaration"],
          ].map(([value, label], i) => (
            <div
              key={value}
              style={{
                marginBottom: 34,
                opacity: show(f, i * 45),
                translate: `${(1 - show(f, i * 45)) * 25}px 0`,
              }}
            >
              <div
                style={{
                  fontFamily: display,
                  fontSize: 65,
                  color: i === 2 ? colors.gold : colors.white,
                }}
              >
                {value}
              </div>
              <div style={{ fontSize: 24, color: colors.muted }}>{label}</div>
            </div>
          ))}
        </div>
        <div
          style={{
            position: "absolute",
            right: 95,
            bottom: 130,
            width: 670,
            fontSize: 25,
            lineHeight: 1.5,
            textAlign: "right",
            color: colors.gold,
            opacity: show(f, 150),
          }}
        >
          Radar association and identity unconfirmed.
          <br />
          Review cues do not establish hostile intent.
        </div>
      </Film>
    );
  },
});

export const Countdown = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Film>
        <Chart
          time={5400}
          from={[720, 535, 920, 517.5]}
          to={[780, 540, 800, 450]}
          projection={interpolate(f, [15, 250], [0, 1], clamp)}
          radar={false}
        />
        <AbsoluteFill
          style={{
            background: "linear-gradient(90deg,#07131ce8,transparent 77%)",
          }}
        />
        <div
          style={{ position: "absolute", left: 100, top: 155, fontSize: 29 }}
        >
          Expected cable crossing
        </div>
        <Text y={210} size={218} width={1200}>
          {clock(assessment.eta_expected_s)}
        </Text>
        <div
          style={{
            position: "absolute",
            left: 105,
            top: 470,
            fontSize: 30,
            lineHeight: 1.5,
            color: colors.muted,
          }}
        >
          Projected from the current
          <br />
          9.1 kn speed and 350.3° course.
        </div>
        <div
          style={{
            position: "absolute",
            left: 105,
            top: 690,
            opacity: show(f, 75),
          }}
        >
          <div style={{ fontSize: 25, color: colors.gold }}>
            Earliest planning estimate
          </div>
          <div
            style={{
              fontFamily: display,
              fontSize: 95,
              color: colors.gold,
              lineHeight: 1.2,
            }}
          >
            01:01:15
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            right: 95,
            bottom: 125,
            width: 600,
            fontSize: 24,
            textAlign: "right",
            lineHeight: 1.5,
            color: colors.muted,
          }}
        >
          Earliest uses 20% higher speed.
          <br />
          Planning assumptions, not confidence bounds.
        </div>
      </Film>
    );
  },
});

export const Options = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const x = (m: number) => 650 + (m / 260) * 1100;
    return (
      <Film>
        <Chart time={5400} dim={0.78} radar={false} />
        <Text y={125} size={100} width={1400}>
          What arrives in time?
        </Text>
        <div
          style={{
            position: "absolute",
            left: 105,
            top: 260,
            fontSize: 25,
            color: colors.muted,
          }}
        >
          Assumed arrival times compared with the earliest crossing estimate.
        </div>
        <svg
          width="1920"
          height="1080"
          style={{ position: "absolute", inset: 0 }}
        >
          <line
            x1={x(61.25)}
            x2={x(61.25)}
            y1="350"
            y2="850"
            stroke={colors.gold}
            strokeDasharray="6 8"
            strokeWidth="2"
          />
          <text
            x={x(61.25) + 13}
            y="330"
            fill={colors.gold}
            fontFamily={body}
            fontSize="23"
          >
            61 min 15 s / earliest crossing
          </text>
          {[
            assessment.options[2],
            assessment.options[0],
            assessment.options[1],
            assessment.options[3],
          ].map((o, i) => {
            const y = 420 + i * 130,
              minutes = o.eta_s / 60;
            const names = [
              "VHF hail",
              "Patrol aircraft",
              "Patrol ship",
              "Next satellite look",
            ];
            return (
              <g key={o.asset}>
                <text
                  x="105"
                  y={y + 9}
                  fontFamily={body}
                  fontSize="30"
                  fill={colors.white}
                >
                  {names[i]}
                </text>
                <line
                  x1={x(0)}
                  x2={x(0) + (x(minutes) - x(0)) * show(f, i * 22, 50)}
                  y1={y}
                  y2={y}
                  stroke={o.in_time ? colors.gold : "#728791"}
                  strokeWidth="9"
                />
                <text
                  x={x(minutes) + 17}
                  y={y + 10}
                  fill={colors.white}
                  fontFamily={display}
                  fontSize="42"
                  opacity={show(f, i * 22 + 40)}
                >
                  {Math.round(minutes)} min
                </text>
                <text
                  x="105"
                  y={y + 42}
                  fontFamily={body}
                  fontSize="21"
                  fill={o.in_time ? colors.gold : colors.muted}
                >
                  {o.in_time
                    ? "Within the planning window"
                    : "After the planning window"}
                </text>
              </g>
            );
          })}
          {[0, 60, 120, 180, 240].map((m) => (
            <text
              key={m}
              x={x(m)}
              y="930"
              fill={colors.muted}
              fontFamily={body}
              fontSize="22"
              textAnchor="middle"
            >
              {m} min
            </text>
          ))}
        </svg>
      </Film>
    );
  },
});

export const Decision = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    return (
      <Film
        context="Recorded offline exercise / no operational action sent"
        credit="Actual operator-review interaction from the fictional replay"
      >
        <Video
          muted
          objectFit="cover"
          src={staticFile("recordings/review.mp4")}
          trimBefore={5.2 * fps}
          style={{
            position: "absolute",
            width: 1920,
            height: 1080,
            scale: interpolate(f, [0, 240], [1.45, 1.9], clamp),
            transformOrigin: "50% 53%",
          }}
        />
        <AbsoluteFill
          style={{
            background: "linear-gradient(0deg,#06111eea 5%,#06111e00 60%)",
          }}
        />
        <div style={{ position: "absolute", left: 95, bottom: 125 }}>
          <div style={{ fontFamily: display, fontSize: 100, lineHeight: 1 }}>
            A human decides.
          </div>
          <div style={{ fontSize: 26, color: colors.muted, marginTop: 22 }}>
            Review uncertainty. Confirm timing. Record an exercise decision.
          </div>
        </div>
      </Film>
    );
  },
});

export const Closing = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Film
        context="EUDIS Challenge 3 / Ireland"
        credit="Coastline: Natural Earth, public domain · scenario and cable geometry: simulated"
      >
        <Chart
          time={5400}
          from={[650, 530, 1000, 562.5]}
          to={[60, 130, 1950, 1096.875]}
          dim={0.55}
        />
        <div
          style={{
            position: "absolute",
            left: 95,
            top: 220,
            opacity: show(f, 0, 18),
          }}
        >
          <div
            style={{
              fontFamily: display,
              fontSize: 210,
              fontWeight: 700,
              lineHeight: 0.9,
              letterSpacing: -3,
            }}
          >
            ARGUS MARA
          </div>
          <div style={{ fontSize: 39, marginTop: 55, lineHeight: 1.4 }}>
            See the evidence.
            <br />
            Understand the response window.
          </div>
          <div style={{ fontSize: 25, color: colors.gold, marginTop: 90 }}>
            Offline replay · explainable rules · human approval
          </div>
        </div>
      </Film>
    );
  },
});

export const Trailer = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Audio src={staticFile("film-soundtrack.wav")} volume={0.65} />
      <Track name="Maritime film">
        <Opening durationInFrames={5 * fps} />
        <Reveal from={5 * fps} durationInFrames={6 * fps} />
        <Signals from={11 * fps} durationInFrames={8 * fps} />
        <Approach from={19 * fps} durationInFrames={9 * fps} />
        <Countdown from={28 * fps} durationInFrames={10 * fps} />
        <Options from={38 * fps} durationInFrames={10 * fps} />
        <Decision from={48 * fps} durationInFrames={8 * fps} />
        <Closing from={56 * fps} durationInFrames={4 * fps} />
      </Track>
    </AbsoluteFill>
  );
};
export const ShortTrailer = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Audio src={staticFile("short-soundtrack.wav")} volume={0.65} />
      <Track name="Maritime short film">
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
