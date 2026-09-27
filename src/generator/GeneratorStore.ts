import type { GeneratorState } from "./GeneratorModels";

type Listener = (state: GeneratorState) => void;
type Updater = (state: GeneratorState) => GeneratorState;

export class GeneratorStore {
  private state: GeneratorState;
  private readonly listeners = new Set<Listener>();

  constructor(initialState: GeneratorState) {
    this.state = initialState;
  }

  getState(): GeneratorState {
    return this.state;
  }

  setState(nextState: GeneratorState): void {
    this.state = nextState;
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }

  update(updater: Updater): void {
    this.setState(updater(this.state));
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
