import React from "react";
import { AbsoluteFill, Img, Sequence, staticFile, useCurrentFrame, interpolate, delayRender, continueRender } from "remotion";
import { Audio } from "@remotion/media";
import { loadFont } from "@remotion/fonts";

const handle = delayRender("Native film typography");
Promise.all([
  loadFont({ family: "Barlow", url: staticFile("fonts/barlow-condensed-latin-700-normal.woff2"), weight: "700" }),
  loadFont({ family: "DM Sans", url: staticFile("fonts/dm-sans-latin-400-normal.woff2"), weight: "400" }),
]).then(() => continueRender(handle));
const gold = "#e7bd76", white = "#f6f3e9", muted = "#b3c8ce";
const ease = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const reveal = (f: number, at = 0) => interpolate(f, [at, at + 18], [0, 1], ease);

const Frame: React.FC<{children: React.ReactNode; credit: string; section: string}> = ({children, credit, section}) => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{background: "#0a1823", color: white, fontFamily: "DM Sans", overflow: "hidden"}}>
    {children}
    <div style={{position: "absolute", top: 0, height: 62, width: "100%", background: "#07121b", borderBottom: "1px solid #334651"}} />
    <div style={{position: "absolute", bottom: 0, height: 68, width: "100%", background: "#07121b", borderTop: "1px solid #334651"}} />
    <div style={{position: "absolute", left: 54, top: 19, fontSize: 18, letterSpacing: 2}}>ARGUS MARA <span style={{color: gold, marginLeft: 26}}>{section}</span></div>
    <div style={{position: "absolute", right: 54, top: 20, fontSize: 17, color: muted}}>ACTUAL APPLICATION · CACHED OBSERVATIONS</div>
    <div style={{position: "absolute", left: 54, bottom: 24, fontSize: 16, color: muted}}>{credit}</div>
    <div style={{position: "absolute", bottom: 0, left: 0, height: 3, width: `${Math.min(100, f / 3)}%`, background: gold}} />
  </AbsoluteFill>;
};

const Shot: React.FC<{name: string; report?: boolean; overview?: boolean; queue?: boolean}> = ({name, report = false, overview = false, queue = false}) => {
  const f = useCurrentFrame();
  const drift = interpolate(f, [0, 300], [0, 28], ease);
  return <div style={{position: "absolute", left: 655, top: 154, width: 1210, height: 775, overflow: "hidden", border: "1px solid #49616d", boxShadow: "0 30px 90px #0008", transform: `translateX(${(1-reveal(f))*75}px)`, opacity: reveal(f)}}>
    <Img src={staticFile(`native/${name}.png`)} style={{position: "absolute", maxWidth: "none", width: queue ? 1800 : overview ? 1480 : report ? 1650 : 1920, left: queue ? -50 : overview ? -260 : report ? -130 : -695, top: report ? -40 : -85, transform: `translateY(${-drift}px)`}} />
    <div style={{position: "absolute", bottom: 0, left: 0, right: 0, height: 65, background: "linear-gradient(transparent,#07121b)"}} />
  </div>;
};

const Copy: React.FC<{number: string; title: React.ReactNode; children: React.ReactNode; tag?: string}> = ({number, title, children, tag}) => {
  const f = useCurrentFrame();
  return <div style={{position: "absolute", left: 62, top: 165, width: 545}}>
    <div style={{color: gold, fontSize: 21, letterSpacing: 3, opacity: reveal(f)}}>{number}</div>
    <div style={{fontFamily: "Barlow", fontWeight: 700, fontSize: 98, lineHeight: .96, letterSpacing: -1, marginTop: 30, opacity: reveal(f, 3), transform: `translateY(${(1-reveal(f,3))*25}px)`}}>{title}</div>
    <div style={{fontSize: 27, lineHeight: 1.5, color: muted, marginTop: 36, opacity: reveal(f, 12)}}>{children}</div>
    {tag && <div style={{marginTop: 40, paddingTop: 22, borderTop: "1px solid #465966", color: gold, fontSize: 20, lineHeight: 1.5, opacity: reveal(f, 24)}}>{tag}</div>}
  </div>;
};

export const Opening = () => {
  const f = useCurrentFrame();
  return <Frame section="MARITIME INTELLIGENCE" credit="Native desktop application · real cached AIS · EMODnet bathymetry · approximate historical cable reference">
    <Img src={staticFile("native/overview.png")} style={{width: 1920, height: 1012, position: "absolute", top: 39, transform: `scale(${1+f*.00015})`}} />
    <AbsoluteFill style={{background: "linear-gradient(90deg,#07121bf5 0%,#07121bdf 32%,#07121b44 68%,transparent)"}} />
    <div style={{position: "absolute", left: 65, top: 240, opacity: reveal(f)}}>
      <div style={{fontSize: 23, color: gold, letterSpacing: 5}}>FROM OBSERVATION TO REVIEW</div>
      <div style={{fontFamily: "Barlow", fontSize: 190, lineHeight: .95, marginTop: 28}}>ARGUS<br/>MARA</div>
      <div style={{fontSize: 31, lineHeight: 1.45, marginTop: 32}}>AIS. Satellite imagery.<br/>The evidence in one workspace.</div>
    </div>
  </Frame>;
};

export const Reveal = () => <Frame section="01 / RECEIVED AIS" credit="AISstream / retained team archive · snapshot 17 Oct 2026, 10:23 UTC · partial received coverage">
  <Shot name="ais" />
  <Copy number="01 / RECEIVE" title={<>Follow the<br/>reported track.</>} tag="2,138 plotted positions in this cached snapshot. No live refresh during filming.">
    AISstream vessel positions.<br/>Source timestamps, speed and course.<br/>Retained history with gaps preserved.
  </Copy>
</Frame>;

export const Signals = () => {
  const f = useCurrentFrame();
  const cables = f >= 110;
  return <Frame section="02 / REFERENCE DATASETS" credit="NGA World Port Index · Marine Atlas / MIDA CC BY 4.0 · TeleGeography historical v2 CC BY-NC-SA 3.0">
    <Shot name={cables ? "cables" : "ports"} />
    <Copy number="02 / ADD CONTEXT" title={<>Know what<br/>is nearby.</>} tag="Historical cable geometry is approximate reference data, not a surveyed asset position.">
      <div style={{marginBottom: 16}}><b style={{color: white}}>3,805</b> World Port Index entries</div>
      <div style={{marginBottom: 16}}><b style={{color: white}}>142</b> Irish port records</div>
      <div><b style={{color: white}}>497</b> historical cable routes</div>
    </Copy>
  </Frame>;
};

export const Approach = () => {
  const f = useCurrentFrame();
  return <Frame section="03 / SATELLITE WORKSPACE" credit="Sentinel-2 real optical pixels · acquisition 13 Oct 2026, 11:46 UTC · saved review shown">
    <Shot name={f < 85 ? "coast-watch" : "satellite-review"} />
    <Copy number="03 / INSPECT" title={<>Open the<br/>source pixels.</>} tag="Sentinel-1 radar and Sentinel-2 optical catalogues. GFW radar detections are an optional delayed source.">
      Coast Watch organises imagery along the Irish coast.<br/><br/>Inspect georeferenced crops and keep acquisition time attached.
    </Copy>
  </Frame>;
};

export const Countdown = () => <Frame section="04 / TIME-ALIGNED COMPARISON" credit="Actual saved Sentinel-2 review · AI contact suggestion = assumption / unreviewed · identity unknown">
  <Shot name="contact-comparison" />
  <Copy number="04 / COMPARE" title={<>Same place.<br/>Same time?</>} tag="This image has no contemporaneous AIS in the archive. Current positions cannot identify a past contact.">
    Compare image acquisition time with retained AIS when available.<br/><br/>Inspect the crop behind each AI-assisted suggestion.
  </Copy>
</Frame>;

export const Options = () => <Frame section="05 / ANALYST REVIEW" credit="Real received AIS history · rule-generated review leads · a gap or motion anomaly does not establish intent">
  <Shot name="overview" queue />
  <Copy number="05 / REVIEW" title={<>A lead.<br/>Then a check.</>} tag="The actual queue contains two history leads. Each requires an analyst to inspect the evidence.">
    Check recorded vessel histories.<br/>Surface motion and data-quality issues.<br/><br/>Keep sources, gaps and uncertainty visible.
  </Copy>
</Frame>;

export const Decision = () => <Frame section="06 / EVIDENCE-BASED REPORTING" credit="Actual native report editor · dated cached AIS · no report submitted or shared during filming">
  <Shot name="analyst-report" report />
  <Copy number="06 / DOCUMENT" title={<>Build the<br/>assessment.</>} tag="Human approval stays explicit. No automatic operational response.">
    Prefill available vessel facts.<br/>Edit the assessment.<br/>Check the report and export a PDF.<br/><br/>Share only through an explicit operator action.
  </Copy>
</Frame>;

export const Closing = () => {
  const f = useCurrentFrame();
  return <Frame section="EUDIS CHALLENGE 3 / IRELAND" credit="Actual application captures · 17 Oct 2026 · dataset dates and provenance retained · original instrumental / no voiceover">
    <Img src={staticFile("native/overview.png")} style={{width: 1920, position: "absolute", top: 40, opacity: .3, transform: `scale(${1.07-f*.00012})`}} />
    <AbsoluteFill style={{background: "linear-gradient(90deg,#07121bf5,#07121b55)"}} />
    <div style={{position: "absolute", left: 85, top: 270, opacity: reveal(f)}}>
      <div style={{fontFamily: "Barlow", fontSize: 180, lineHeight: 1}}>ARGUS MARA</div>
      <div style={{fontSize: 42, marginTop: 40, lineHeight: 1.45}}>Collect observations.<br/>Compare evidence.<br/>Support analyst review.</div>
      <div style={{fontSize: 23, color: gold, marginTop: 55}}>AIS + satellite imagery + maritime reference data</div>
    </div>
  </Frame>;
};

export const Trailer = () => <AbsoluteFill>
  <Audio src={staticFile("film-soundtrack.wav")} volume={.65} />
  <Sequence durationInFrames={150}><Opening /></Sequence>
  <Sequence from={150} durationInFrames={240}><Reveal /></Sequence>
  <Sequence from={390} durationInFrames={240}><Signals /></Sequence>
  <Sequence from={630} durationInFrames={300}><Approach /></Sequence>
  <Sequence from={930} durationInFrames={300}><Countdown /></Sequence>
  <Sequence from={1230} durationInFrames={240}><Options /></Sequence>
  <Sequence from={1470} durationInFrames={210}><Decision /></Sequence>
  <Sequence from={1680} durationInFrames={120}><Closing /></Sequence>
</AbsoluteFill>;

export const ShortTrailer = () => <AbsoluteFill>
  <Audio src={staticFile("short-soundtrack.wav")} volume={.65} />
  <Sequence durationInFrames={90}><Opening /></Sequence>
  <Sequence from={90} durationInFrames={150}><Reveal /></Sequence>
  <Sequence from={240} durationInFrames={180}><Signals /></Sequence>
  <Sequence from={420} durationInFrames={180}><Countdown /></Sequence>
  <Sequence from={600} durationInFrames={180}><Decision /></Sequence>
  <Sequence from={780} durationInFrames={120}><Closing /></Sequence>
</AbsoluteFill>;
