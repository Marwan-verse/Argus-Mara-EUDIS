import { mount } from "svelte";
import Recorder from "./Recorder.svelte";
const data = JSON.parse(document.getElementById("recorded-data").textContent);
mount(Recorder, { target: document.getElementById("app"), props: { data } });
