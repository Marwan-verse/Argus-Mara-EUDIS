import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

const cyan = "#5ee8d4",
  gold = "#e9bb64";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export const RadarChart: React.FC<{ approach?: boolean }> = ({
  approach = false,
}) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = interpolate(f, [0, 8 * fps], [0, 1], clamp);
  const x = approach ? 380 + progress * 310 : 210 + progress * 480,
    y = approach ? 375 - progress * 125 : 435 - progress * 165;
  const reception = approach || f < 1.6 * fps || f > 6.5 * fps;
  const ping = (f % (2 * fps)) / (2 * fps);
  return (
    <svg
      viewBox="0 0 1000 650"
      width="100%"
      height="100%"
      style={{ background: "#0b1c24" }}
    >
      <defs>
        <pattern
          id="chartgrid"
          width="75"
          height="75"
          patternUnits="userSpaceOnUse"
        >
          <path d="M75 0H0V75" fill="none" stroke="#24424d" strokeWidth="1" />
        </pattern>
        <linearGradient id="scan">
          <stop stopColor={cyan} stopOpacity="0" />
          <stop offset="1" stopColor={cyan} stopOpacity=".22" />
        </linearGradient>
      </defs>
      <rect width="1000" height="650" fill="url(#chartgrid)" />
      <path
        d="M0 0H160L145 85 200 130 155 225 180 280 125 350 155 440 95 500 120 570 80 650H0Z"
        fill="#19353e"
        stroke="#648c92"
        strokeWidth="2"
      />
      <path
        d="M1000 0H900L870 100 910 180 860 260 895 355 850 420 885 530 845 650H1000Z"
        fill="#19353e"
        stroke="#648c92"
        strokeWidth="2"
      />
      <text
        x="30"
        y="340"
        fill="#8faeb6"
        fontSize="24"
        transform="rotate(-90 30 340)"
      >
        IRELAND
      </text>
      <text
        x="935"
        y="335"
        fill="#8faeb6"
        fontSize="24"
        transform="rotate(90 935 335)"
      >
        WALES
      </text>
      <path
        d="M130 220Q450 180 875 290"
        fill="none"
        stroke={cyan}
        strokeWidth="4"
      />
      <text x="340" y="160" fill={cyan} fontFamily="Consolas" fontSize="18">
        ILLUSTRATIVE CABLE ROUTE
      </text>
      <path
        d="M210 435L380 375"
        fill="none"
        stroke={gold}
        strokeWidth="3"
        strokeDasharray={approach ? "0" : "7 12"}
      />
      <path
        d={`M${approach ? 380 : 210} ${approach ? 375 : 435}L${x} ${y}`}
        fill="none"
        stroke={gold}
        strokeWidth="3"
      />
      {approach && (
        <path
          d={`M${x} ${y}L770 135`}
          fill="none"
          stroke={gold}
          strokeWidth="2"
          strokeDasharray="7 10"
          strokeDashoffset={-f * 1.6}
        />
      )}
      <g
        opacity={reception ? 1 : 0.22}
        transform={`translate(${x} ${y}) rotate(${approach ? 38 : 65})`}
      >
        <path d="M0 -19L10 13 0 8 -10 13Z" fill={gold} />
      </g>
      <circle
        cx="510"
        cy="305"
        r={18 + ping * 105}
        fill="none"
        stroke={cyan}
        strokeWidth="2"
        opacity={1 - ping}
      />
      <path
        d="M510 293L522 305 510 317 498 305Z"
        fill="none"
        stroke={cyan}
        strokeWidth="2"
      />
      <text x="540" y="302" fill={cyan} fontSize="18" fontFamily="Consolas">
        RADAR · SIMULATED
      </text>
      <text x="540" y="327" fill="#a9c4c8" fontSize="17" fontFamily="Consolas">
        ASSOCIATION UNCONFIRMED
      </text>
      <rect
        x={-200 + ((f % 180) / 180) * 1400}
        width="110"
        height="650"
        fill="url(#scan)"
      />
      <rect x="25" y="25" width="530" height="65" fill="#071116e6" />
      <text x="44" y="51" fill={gold} fontFamily="Consolas" fontSize="20">
        CORMORANT STAR · FICTIONAL
      </text>
      <text
        x="44"
        y="76"
        fill={reception ? cyan : gold}
        fontFamily="Consolas"
        fontSize="17"
      >
        {approach
          ? "SIMULATED COURSE PROJECTION"
          : reception
            ? "AIS RECEIVED"
            : "AIS RECEPTION GAP · CAUSE UNKNOWN"}
      </text>
      <text x="28" y="615" fill="#9fb6bf" fontSize="16" fontFamily="Consolas">
        ANIMATED EXERCISE DIAGRAM · NOT NAVIGATION DATA
      </text>
    </svg>
  );
};

export const Orbit = () => {
  const f = useCurrentFrame();
  return (
    <svg
      width="1920"
      height="1080"
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        opacity: 0.48,
      }}
    >
      <g transform={`rotate(${f * 0.45} 1390 520)`}>
        <circle
          cx="1390"
          cy="520"
          r="380"
          fill="none"
          stroke={cyan}
          strokeWidth="2"
          strokeDasharray="180 2200"
        />
        <circle cx="1770" cy="520" r="7" fill={cyan} />
      </g>
      {[0, 1, 2].map((i) => (
        <circle
          key={i}
          cx="1350"
          cy="530"
          r={20 + ((f + i * 30) % 100) * 2.4}
          fill="none"
          stroke={gold}
          strokeWidth="2"
          opacity={1 - ((f + i * 30) % 100) / 100}
        />
      ))}
    </svg>
  );
};

export const TimerMotion = () => {
  const f = useCurrentFrame();
  return (
    <svg
      width="1920"
      height="1080"
      style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
    >
      <g transform={`rotate(${f * 0.6} 960 520)`}>
        <circle
          cx="960"
          cy="520"
          r="405"
          fill="none"
          stroke={gold}
          strokeOpacity=".14"
          strokeWidth="2"
          strokeDasharray="6 18"
        />
        <circle
          cx="960"
          cy="520"
          r="418"
          fill="none"
          stroke={cyan}
          strokeOpacity=".3"
          strokeWidth="3"
          strokeDasharray="260 2400"
        />
      </g>
      <path d="M210 830H1710" stroke="#29444c" />
      <path
        d="M210 830H1710"
        stroke={gold}
        strokeWidth="3"
        strokeDasharray="1500"
        strokeDashoffset={interpolate(f, [0, 390], [1500, 0], clamp)}
      />
    </svg>
  );
};

export const ResponseBars = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div
      style={{
        position: "absolute",
        left: 910,
        right: 100,
        top: 180,
        pointerEvents: "none",
      }}
    >
      {[0.07, 0.3, 0.85, 0.96].map((target, i) => (
        <div key={i} style={{ height: 148, position: "relative" }}>
          <div
            style={{
              position: "absolute",
              bottom: 0,
              height: 4,
              background: i < 2 ? cyan : gold,
              width: `${target * 100 * spring({ frame: f - i * 12, fps, config: { damping: 24 }, durationInFrames: 70 })}%`,
              boxShadow: `0 0 15px ${i < 2 ? cyan : gold}50`,
            }}
          />
        </div>
      ))}
    </div>
  );
};
