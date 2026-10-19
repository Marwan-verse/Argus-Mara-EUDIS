import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { coastRings } from "./coast";
import { exercise } from "./evidence";

export const colors = {
  sea: "#142e40",
  land: "#34515d",
  shore: "#71929b",
  white: "#f6f3e9",
  gold: "#e7bd76",
  muted: "#b2c6ce",
};
export const clamp = {
  extrapolateLeft: "clamp",
  extrapolateRight: "clamp",
} as const;
export const gx = (lon: number) => (lon + 11.5) * 200;
export const gy = (lat: number) => (56 - lat) * 300;
const land = coastRings.map(
  (r) =>
    r
      .map(
        (p, i) =>
          `${i ? "L" : "M"}${gx(p[0]).toFixed(2)} ${gy(p[1]).toFixed(2)}`,
      )
      .join(" ") + "Z",
);
const cable = exercise.cables[0].path;
const fixes = exercise.vessels[0].track;
const detection = exercise.detections[0];
const projected = (() => {
  const fix = fixes.find((p) => p.t === 5400)!;
  const a = (fix.cog_deg * Math.PI) / 180,
    dx = Math.sin(a) / Math.cos((fix.lat * Math.PI) / 180),
    dy = Math.cos(a);
  let end = [fix.lon, 53.36],
    nearest = Infinity;
  for (let i = 1; i < cable.length; i++) {
    const p = cable[i - 1],
      q = cable[i],
      sx = q[1] - p[1],
      sy = q[0] - p[0],
      det = dx * sy - dy * sx;
    if (!det) continue;
    const xx = p[1] - fix.lon,
      yy = p[0] - fix.lat;
    const t = (xx * sy - yy * sx) / det,
      u = (xx * dy - yy * dx) / det;
    if (t > 0 && u >= 0 && u <= 1 && t < nearest) {
      nearest = t;
      end = [fix.lon + t * dx, fix.lat + t * dy];
    }
  }
  return end;
})();
type View = [number, number, number, number];
export const Chart: React.FC<{
  time: number;
  from?: View;
  to?: View;
  projection?: number;
  radar?: boolean;
  dim?: number;
}> = ({
  time,
  from = [650, 530, 1000, 562.5],
  to = from,
  projection = 0,
  radar = true,
  dim = 0,
}) => {
  const f = useCurrentFrame();
  const camera = interpolate(f, [0, 330], [0, 1], clamp);
  const view = from.map((n, i) => n + (to[i] - n) * camera).join(" ");
  const received = fixes.filter((p) => p.t <= time);
  const latest = received[received.length - 1] || fixes[0];
  const next = fixes.find((p) => p.t > time);
  const gap = !!next && next.t - latest.t > 120 && time >= 1800;
  const mix =
    next && !gap ? Math.min(1, (time - latest.t) / (next.t - latest.t)) : 0;
  const lon = latest.lon + (next ? next.lon - latest.lon : 0) * mix,
    lat = latest.lat + (next ? next.lat - latest.lat : 0) * mix;
  const path = received
    .map(
      (p, i) =>
        `${i === 0 || p.t - received[i - 1].t > 120 ? "M" : "L"}${gx(p.lon)} ${gy(p.lat)}`,
    )
    .join(" ");
  const px = gx(lon),
    py = gy(lat);
  return (
    <AbsoluteFill style={{ background: colors.sea }}>
      <svg
        width="1920"
        height="1080"
        viewBox={view}
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <linearGradient id="water" x2="1" y2="1">
            <stop stopColor="#1b3a4e" />
            <stop offset="1" stopColor="#102636" />
          </linearGradient>
        </defs>
        <rect
          x="-2000"
          y="-2000"
          width="7000"
          height="7000"
          fill="url(#water)"
        />
        {[50, 51, 52, 53, 54, 55, 56].map((lat) => (
          <line
            key={lat}
            x1="-2000"
            x2="4000"
            y1={gy(lat)}
            y2={gy(lat)}
            stroke="#78939b"
            strokeOpacity=".09"
            strokeWidth=".7"
          />
        ))}
        {[-12, -10, -8, -6, -4, -2].map((lon) => (
          <line
            key={lon}
            x1={gx(lon)}
            x2={gx(lon)}
            y1="-2000"
            y2="4000"
            stroke="#78939b"
            strokeOpacity=".09"
            strokeWidth=".7"
          />
        ))}
        {land.map((d, i) => (
          <path
            key={i}
            d={d}
            fill={colors.land}
            stroke={colors.shore}
            strokeOpacity=".65"
            strokeWidth=".8"
          />
        ))}
        <text
          x="675"
          y="785"
          fontFamily="Barlow"
          fontWeight="700"
          fontSize="55"
          fill="#9fb7be"
          opacity=".35"
          letterSpacing="5"
        >
          IRELAND
        </text>
        <text
          x="1550"
          y="825"
          fontFamily="Barlow"
          fontWeight="700"
          fontSize="32"
          fill="#9fb7be"
          opacity=".35"
          letterSpacing="3"
        >
          WALES
        </text>
        <text
          x="1275"
          y="1010"
          fontFamily="DM Sans"
          fontSize="16"
          fill="#8da9b4"
          opacity=".5"
        >
          Irish Sea
        </text>
        <path
          d={cable
            .map((p, i) => `${i ? "L" : "M"}${gx(p[1])} ${gy(p[0])}`)
            .join(" ")}
          fill="none"
          stroke={colors.gold}
          strokeWidth="2.5"
        />
        <text
          x={gx(-5.95)}
          y={gy(53.35) - 12}
          fontFamily="DM Sans"
          fontSize="11"
          fill={colors.gold}
        >
          Illustrative cable route
        </text>
        <circle cx={gx(-6.05)} cy={gy(53.35)} r="3.5" fill={colors.gold} />
        <text
          x={gx(-6.08) - 38}
          y={gy(53.35) - 10}
          fontFamily="DM Sans"
          fontSize="11"
          fill={colors.white}
        >
          Dublin
        </text>
        <path
          d={path}
          fill="none"
          stroke={colors.white}
          strokeWidth="2"
          strokeLinejoin="round"
        />
        {gap ? (
          <g>
            <circle cx={px} cy={py} r="5" fill="none" stroke={colors.white} />
            <text
              x={px + 13}
              y={py + 5}
              fill={colors.muted}
              fontFamily="DM Sans"
              fontSize="12"
            >
              Last received fix
            </text>
          </g>
        ) : (
          <g transform={`translate(${px} ${py}) rotate(${latest.cog_deg})`}>
            <path d="M0 -8L4 6 0 4 -4 6Z" fill={colors.white} />
          </g>
        )}
        {!gap && (
          <text
            x={px + 14}
            y={py + 4}
            fill={colors.white}
            fontFamily="DM Sans"
            fontSize="12"
          >
            CORMORANT STAR
          </text>
        )}
        {radar && time >= 2400 && (
          <g>
            <path
              d={`M${gx(detection.lon)} ${gy(detection.lat) - 6}l6 6 -6 6 -6 -6Z`}
              fill="none"
              stroke={colors.gold}
              strokeWidth="1.5"
            />
            <text
              x={gx(detection.lon) + 12}
              y={gy(detection.lat) + 5}
              fontSize="11"
              fontFamily="DM Sans"
              fill={colors.gold}
            >
              Separate radar contact
            </text>
          </g>
        )}
        {projection > 0 && (
          <g>
            <line
              x1={px}
              y1={py}
              x2={px + (gx(projected[0]) - px) * projection}
              y2={py + (gy(projected[1]) - py) * projection}
              stroke={colors.gold}
              strokeWidth="2.4"
              strokeDasharray="5 5"
            />
            <circle
              cx={gx(projected[0])}
              cy={gy(projected[1])}
              r="7"
              fill={colors.sea}
              stroke={colors.gold}
              strokeWidth="2"
            />
            <text
              x={gx(projected[0]) + 15}
              y={gy(projected[1]) + 30}
              fontSize="12"
              fontFamily="DM Sans"
              fill={colors.gold}
            >
              Projected crossing
            </text>
          </g>
        )}
      </svg>
      <AbsoluteFill style={{ background: `rgba(4,13,20,${dim})` }} />
    </AbsoluteFill>
  );
};
