import { useState } from "react";

// The NBA publishes logos made for dark backgrounds ("D") and light ones ("L").
// Try the dark version first, fall back to the light one, then to nothing.
export default function TeamLogo({ url, size = 36 }) {
  const darkUrl = url?.replace("/global/L/", "/global/D/");
  const [src, setSrc] = useState(darkUrl);
  if (!src) return <span className="logo logo-missing" style={{ width: size, height: size }} />;
  return (
    <img
      className="logo"
      src={src}
      width={size}
      height={size}
      alt=""
      loading="lazy"
      onError={() => setSrc(src === darkUrl && url !== darkUrl ? url : null)}
    />
  );
}
