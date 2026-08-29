import { RtaiRuntimeProvider } from "./runtime/RtaiRuntimeProvider";
import { OpenChamberChat } from "./components/OpenChamberChat";

export function App() {
  return (
    <RtaiRuntimeProvider>
      <OpenChamberChat />
    </RtaiRuntimeProvider>
  );
}
