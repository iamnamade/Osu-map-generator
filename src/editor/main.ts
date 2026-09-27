import { EditorApp } from "./EditorApp";
import { initializeProjectMapCatalog } from "../shared/mapCatalog";

const root = document.querySelector<HTMLDivElement>("#app");

if (!root) {
  throw new Error("Editor root was not found.");
}

let app: EditorApp | null = null;

void initializeProjectMapCatalog().then(async () => {
  app = new EditorApp(root);
  await app.start();
});

window.addEventListener("beforeunload", () => {
  app?.dispose();
});
