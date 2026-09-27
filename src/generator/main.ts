import { GeneratorApp } from "./GeneratorApp";
import "./styles/generator.css";

const root = document.querySelector<HTMLDivElement>("#app");

if (!root) {
  throw new Error("Generator root was not found.");
}

const app = new GeneratorApp(root);
void app.start();

window.addEventListener("beforeunload", () => {
  app.dispose();
});
