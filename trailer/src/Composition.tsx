import React from "react";
import {
  AbsoluteFill,
  CanvasImage,
  Interactive,
  spring,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Audio } from "@remotion/media";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { slide } from "@remotion/transitions/slide";
import { fade } from "@remotion/transitions/fade";
import { RadarChart, Orbit, TimerMotion, ResponseBars } from "./Motion";
const cyan = "#5ee8d4",
  gold = "#e9bb64",
  ink = "#071116",
  mono = "Consolas, monospace";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const Shell: React.FC<{ children: React.ReactNode; label?: string }> = ({
  children,
  label = "FICTIONAL EXERCISE · SIMULATED OBSERVATIONS",
}) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: ink,
        color: "#f2f5ef",
        fontFamily: "Segoe UI, Arial, sans-serif",
        overflow: "hidden",
      }}
    >
      <AbsoluteFill
        style={{
          backgroundImage:
            "linear-gradient(#33505a18 1px,transparent 1px),linear-gradient(90deg,#33505a18 1px,transparent 1px)",
          backgroundSize: "90px 90px",
          backgroundPosition: `${f * 0.2}px ${f * 0.1}px`,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 45,
          left: 72,
          fontSize: 22,
          letterSpacing: 4,
          color: gold,
        }}
      >
        ◉ ARGUS MARA
      </div>
      <div
        style={{
          position: "absolute",
          right: 72,
          top: 49,
          fontFamily: mono,
          fontSize: 16,
          color: "#9eafb3",
        }}
      >
        {label}
      </div>
      <AbsoluteFill
        style={{
          translate: `${interpolate(f, [0, 20], [55, 0], clamp)}px 0`,
          opacity: interpolate(f, [0, 14], [0, 1], clamp),
        }}
      >
        {children}
      </AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 72,
          right: 72,
          top: 92,
          height: 1,
          background: "#284750",
        }}
      >
        <div
          style={{
            height: 1,
            width: `${((f % 240) / 240) * 100}%`,
            background: cyan,
          }}
        />
      </div>
      <div
        style={{
          position: "absolute",
          left: 72,
          right: 72,
          bottom: 44,
          display: "flex",
          justifyContent: "space-between",
          fontFamily: mono,
          fontSize: 17,
          color: "#92a9b0",
          letterSpacing: 2,
        }}
      >
        <span>EUDIS CHALLENGE 3 / IRELAND</span>
        <span>OPERATOR REVIEW REQUIRED</span>
      </div>
    </AbsoluteFill>
  );
};
const Kicker: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      fontFamily: mono,
      fontSize: 22,
      letterSpacing: 5,
      color: cyan,
      marginBottom: 26,
    }}
  >
    {children}
  </div>
);
const Head: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div
      style={{
        translate: `0 ${60 * (1 - spring({ frame: f - 6, fps, config: { damping: 22 } }))}px`,
        opacity: interpolate(f, [6, 20], [0, 1], clamp),
        fontSize: 91,
        lineHeight: 1.05,
        letterSpacing: -3,
        fontWeight: 650,
      }}
    >
      {children}
    </div>
  );
};
const Caption: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      position: "absolute",
      bottom: 101,
      left: 200,
      right: 200,
      textAlign: "center",
      fontSize: 28,
      lineHeight: 1.3,
      background: "#071116ed",
      padding: "12px 24px",
    }}
  >
    {children}
  </div>
);
const Frame: React.FC<{ src: string; style?: React.CSSProperties }> = ({
  src,
  style,
}) => {
  const f = useCurrentFrame();
  return (
    <CanvasImage
      src={staticFile(src)}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "contain",
        scale: interpolate(f, [0, 360], [1, 1.07], clamp),
        translate: `${Math.sin(f / 150) * 8}px ${Math.cos(f / 160) * 5}px`,
        ...style,
      }}
    />
  );
};
export const Opening = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    return (
      <Shell label="ILLUSTRATIVE GEOGRAPHY · FICTIONAL EXERCISE">
        <svg width="1920" height="1080" style={{ position: "absolute" }}>
          <defs>
            <radialGradient id="sea">
              <stop stopColor="#123e49" />
              <stop offset="1" stopColor={ink} />
            </radialGradient>
          </defs>
          <ellipse cx="1390" cy="520" rx="650" ry="520" fill="url(#sea)" />
          {[150, 240, 330, 420].map((r) => (
            <circle
              key={r}
              cx="1390"
              cy="520"
              r={r}
              fill="none"
              stroke={cyan}
              strokeOpacity=".12"
            />
          ))}
          <path
            d="M1280 215 L1370 260 1350 320 1410 365 1380 450 1420 500 1380 570 1340 615 1365 680 1310 745 1240 730 1190 680 1210 625 1160 580 1200 535 1170 470 1230 425 1200 370 1245 315Z"
            fill="#183841"
            stroke="#64b4ad"
            strokeWidth="2"
          />
          <path
            d="M1350 530 Q1550 560 1790 450"
            fill="none"
            stroke={cyan}
            strokeWidth="4"
            strokeDasharray="800"
            strokeDashoffset={interpolate(f, [0, 4 * fps], [800, 0], clamp)}
          />
          <circle cx="1350" cy="530" r="7" fill={gold} />
          <text x="1460" y="655" fill="#8ca8ad" fontSize="23" fontFamily={mono}>
            IRISH SEA
          </text>
        </svg>
        <Orbit />
        <div
          style={{
            position: "absolute",
            left: 105,
            top: 300,
            width: 1030,
            opacity: interpolate(f, [0, 24], [0, 1], clamp),
          }}
        >
          <Kicker>VITAL CONNECTIONS. OUT OF SIGHT.</Kicker>
          <Head>
            Beneath the surface.
            <br />
            Before the moment.
          </Head>
          <div style={{ fontSize: 31, color: "#9eb3b9", marginTop: 35 }}>
            A clearer picture. More time to review.
          </div>
        </div>
        <Caption>
          Beneath these waters, vital connections run out of sight.
        </Caption>
      </Shell>
    );
  },
});
export const Reveal = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Shell label="NATIVE APPLICATION · EXISTING WORKSPACE CAPTURE">
        <div
          style={{
            position: "absolute",
            left: 650,
            right: 75,
            top: 145,
            bottom: 165,
            border: "1px solid #40545b",
            boxShadow: "0 40px 100px #0009",
            scale: interpolate(f, [0, 230], [0.96, 1.02], clamp),
          }}
        >
          <Frame src="native-workspace.png" />
        </div>
        <div style={{ position: "absolute", left: 100, top: 270, width: 550 }}>
          <Kicker>INTRODUCING</Kicker>
          <Head>
            ARGUS
            <br />
            <span style={{ color: cyan }}>MARA.</span>
          </Head>
          <div
            style={{
              fontSize: 30,
              color: "#a9bcc1",
              marginTop: 30,
              lineHeight: 1.4,
            }}
          >
            Maritime observations.
            <br />
            One review picture.
          </div>
        </div>
        <Caption>
          Argus Mara brings maritime observations into one review picture.
        </Caption>
      </Shell>
    );
  },
});
export const Signals = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Shell>
        <div
          style={{
            position: "absolute",
            left: 100,
            top: 170,
            width: 1000,
            height: 620,
            border: "1px solid #37515a",
            overflow: "hidden",
          }}
        >
          <RadarChart />
        </div>
        <div style={{ position: "absolute", left: 1160, top: 210, width: 640 }}>
          <Kicker>01 / READ THE SIGNALS</Kicker>
          <Head>
            Something
            <br />
            to review.
          </Head>
          <div
            style={{
              marginTop: 40,
              fontSize: 29,
              lineHeight: 1.5,
              color: "#b1c4c8",
            }}
          >
            {[
              ["20 MIN", "AIS reception gap"],
              ["228 m", "Separate radar contact"],
              ["UNCONFIRMED", "Association and identity"],
            ].map(([a, b], i) => (
              <div
                key={a}
                style={{
                  opacity: interpolate(
                    f,
                    [20 + i * 45, 45 + i * 45],
                    [0, 1],
                    clamp,
                  ),
                  borderTop: "1px solid #34474e",
                  padding: "15px 0",
                }}
              >
                <span
                  style={{
                    color: i === 2 ? gold : cyan,
                    fontFamily: mono,
                    fontSize: 25,
                  }}
                >
                  {a}
                </span>
                <br />
                {b}
              </div>
            ))}
          </div>
        </div>
        <Caption>
          A reception gap. A separate radar contact. Signals that deserve a
          closer look.
        </Caption>
      </Shell>
    );
  },
});
export const Approach = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Shell>
        <div style={{ position: "absolute", left: 100, top: 165 }}>
          <Kicker>02 / EXPLAIN THE CHANGE</Kicker>
          <Head>
            A changing course.
            <br />A developing picture.
          </Head>
        </div>
        <div
          style={{
            position: "absolute",
            left: 1050,
            right: 65,
            top: 170,
            bottom: 210,
            opacity: 0.75,
          }}
        >
          <RadarChart approach />
        </div>
        <div style={{ position: "absolute", left: 105, top: 465, width: 850 }}>
          {[
            ["12.0 → 9.1 kn", "Observed slowdown"],
            ["30°", "Course change"],
            ["CABLE CROSSING", "Constant-course projection"],
          ].map(([a, b], i) => (
            <div
              key={a}
              style={{
                opacity: interpolate(f, [i * 35, 20 + i * 35], [0, 1], clamp),
                display: "flex",
                justifyContent: "space-between",
                padding: "22px 0",
                borderBottom: "1px solid #37505a",
                fontSize: 28,
              }}
            >
              <span style={{ fontFamily: mono, color: gold }}>{a}</span>
              <span style={{ color: "#adbec4" }}>{b}</span>
            </div>
          ))}
          <div
            style={{
              fontFamily: mono,
              fontSize: 20,
              color: "#91a6ad",
              marginTop: 28,
            }}
          >
            CAUSE UNKNOWN · RULE CUES, NOT PROOF OF INTENT
          </div>
        </div>
        <Caption>Explainable rules highlight a situation for review.</Caption>
      </Shell>
    );
  },
});
export const Countdown = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    const seconds = 4411 - Math.floor(f / fps);
    const timer = [
      Math.floor(seconds / 3600),
      Math.floor((seconds % 3600) / 60),
      seconds % 60,
    ]
      .map((x) => String(x).padStart(2, "0"))
      .join(":");
    return (
      <Shell>
        <TimerMotion />
        <AbsoluteFill
          style={{
            background:
              "radial-gradient(ellipse at 50% 55%,#83512130,transparent 65%)",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 185,
            left: 100,
            right: 100,
            textAlign: "center",
          }}
        >
          <Kicker>03 / UNDERSTAND THE WINDOW</Kicker>
          <Head>How much time do we have?</Head>
          <div
            style={{
              fontFamily: mono,
              fontSize: 207,
              letterSpacing: -12,
              color: gold,
              marginTop: 45,
              fontWeight: 700,
              textShadow: `0 0 ${40 + 30 * Math.exp(-(f % fps) / 6)}px #dfa75255`,
              scale: interpolate(f, [0, 30], [0.75, 1], clamp),
            }}
          >
            {timer}
          </div>
          <div style={{ fontSize: 29, color: "#d5e0dd", letterSpacing: 6 }}>
            EXPECTED CABLE CROSSING
          </div>
          <div
            style={{
              fontFamily: mono,
              fontSize: 31,
              marginTop: 40,
              color: cyan,
            }}
          >
            EARLIEST PLANNING ESTIMATE 01:01:15
          </div>
          <div style={{ fontSize: 21, color: "#8fa5ab", marginTop: 23 }}>
            Constant speed and course · assumed cable geometry · not a
            confidence bound
          </div>
        </div>
        <Caption>
          Then comes the practical question: how much time is available?
        </Caption>
      </Shell>
    );
  },
});
export const Options = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Shell>
        <div style={{ position: "absolute", top: 160, left: 100 }}>
          <Kicker>04 / COMPARE THE OPTIONS</Kicker>
          <Head>
            Time changes
            <br />
            the options.
          </Head>
          <div style={{ fontSize: 27, color: "#9fb5bd", marginTop: 30 }}>
            Assumed capabilities.
            <br />
            Compared with the earliest estimate.
          </div>
        </div>
        <div style={{ position: "absolute", left: 910, right: 100, top: 180 }}>
          {[
            ["VHF HAIL", "00:02:00", true],
            ["PATROL AIRCRAFT", "00:39:36", true],
            ["PATROL SHIP", "03:51:50", false],
            ["NEXT SATELLITE LOOK", "04:10:00", false],
          ].map(([name, time, ok], i) => (
            <div
              key={String(name)}
              style={{
                opacity: interpolate(f, [i * 18, 20 + i * 18], [0, 1], clamp),
                borderBottom: "1px solid #344c55",
                padding: "25px 0",
              }}
            >
              <div style={{ fontSize: 24, letterSpacing: 3, color: "#a7b9bf" }}>
                {name}
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginTop: 12,
                }}
              >
                <span style={{ fontSize: 49, fontFamily: mono }}>{time}</span>
                <span
                  style={{
                    fontSize: 22,
                    color: ok ? cyan : gold,
                    padding: "8px 12px",
                    border: `1px solid ${ok ? cyan : gold}`,
                  }}
                >
                  {ok ? "IN TIME" : "LATE"}
                </span>
              </div>
            </div>
          ))}
        </div>
        <ResponseBars />
        <Caption>
          Compare response timing, using visible planning assumptions.
        </Caption>
      </Shell>
    );
  },
});
export const Decision = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Shell>
        <div
          style={{
            position: "absolute",
            left: 85,
            top: 165,
            width: 1050,
            height: 625,
            border: "1px solid #3b555f",
          }}
        >
          <Frame src="review.png" />
        </div>
        <div style={{ position: "absolute", left: 1190, top: 235, right: 80 }}>
          <Kicker>05 / KEEP HUMAN CONTROL</Kicker>
          <Head>
            A human
            <br />
            decides.
          </Head>
          <div
            style={{
              fontSize: 29,
              color: "#b1c4c8",
              lineHeight: 1.5,
              marginTop: 35,
            }}
          >
            Inspect the evidence.
            <br />
            Review the assumptions.
            <br />
            Record the decision.
          </div>
          <div
            style={{
              marginTop: 42,
              padding: 22,
              border: "1px solid #5ee8d4",
              color: cyan,
              fontSize: 23,
              fontFamily: mono,
              opacity: interpolate(f, [25, 65], [0, 1], clamp),
            }}
          >
            EXPLICIT OPERATOR APPROVAL
          </div>
        </div>
        <Caption>
          The operator stays in control. No automatic operational action.
        </Caption>
      </Shell>
    );
  },
});
export const Closing = Interactive.create({
  layout: "absolute-fill",
  Component: () => {
    const f = useCurrentFrame();
    return (
      <Shell label="OFFLINE EXERCISE · INSTRUMENTAL SOUNDTRACK">
        <div
          style={{
            position: "absolute",
            top: 210,
            left: 100,
            right: 100,
            textAlign: "center",
            opacity: interpolate(f, [0, 20], [0, 1], clamp),
          }}
        >
          <div
            style={{
              fontSize: 35,
              color: gold,
              letterSpacing: 12,
              marginBottom: 30,
            }}
          >
            ◉
          </div>
          <div
            style={{
              fontSize: 130,
              letterSpacing: interpolate(f, [0, 65], [35, 13], clamp),
              fontWeight: 650,
              scale: interpolate(f, [0, 70], [0.86, 1], clamp),
            }}
          >
            ARGUS MARA
          </div>
          <div
            style={{
              height: 2,
              width: 250,
              background: cyan,
              margin: "35px auto",
            }}
          />
          <div style={{ fontSize: 43, lineHeight: 1.5 }}>
            See the signals. Understand the window.
            <br />
            <span style={{ color: cyan }}>A human decides.</span>
          </div>
          <div
            style={{
              fontFamily: mono,
              fontSize: 21,
              color: "#9cb0b7",
              marginTop: 45,
            }}
          >
            SPACE-ENABLED MARITIME DOMAIN AWARENESS
          </div>
          <div style={{ fontSize: 17, color: "#829aa3", marginTop: 20 }}>
            Repository application capture · fictional replay · planning and
            response capabilities are assumptions
          </div>
        </div>
      </Shell>
    );
  },
});
export const Trailer = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Audio src={staticFile("soundtrack.wav")} />
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={7 * fps + 12}>
          <Opening />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={8 * fps + 12}>
          <Reveal />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={12 * fps + 12}>
          <Signals />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-bottom" })}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={11 * fps + 12}>
          <Approach />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={13 * fps + 12}>
          <Countdown />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={11 * fps + 12}>
          <Options />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={8 * fps + 12}>
          <Decision />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={5 * fps}>
          <Closing />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
export const ShortTrailer = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Audio src={staticFile("short-soundtrack.wav")} />
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={4 * fps + 12}>
          <Opening />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={4 * fps + 12}>
          <Reveal />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={5 * fps + 12}>
          <Signals />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-bottom" })}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={7 * fps + 12}>
          <Countdown />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={5 * fps + 12}>
          <Decision />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence durationInFrames={5 * fps}>
          <Closing />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
