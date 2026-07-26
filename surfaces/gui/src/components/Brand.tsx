import markUrl from "../assets/mangaba-mark.png";
import mark2xUrl from "../assets/mangaba-mark@2x.png";
import wordmarkUrl from "../assets/mangaba-wordmark.png";
import wordmarkDarkUrl from "../assets/mangaba-wordmark-dark.png";

// A logomarca oficial (mangaba.ai), em um só lugar — telas diferentes escolhem a
// COMPOSIÇÃO, nunca o arquivo. O wordmark tem duas artes porque o traço é grafite:
// no tema escuro ele sumiria, então trocamos a arte, não a opacidade.
//
//   <BrandMark />       — só a manga (barra lateral, splash, favicon)
//   <BrandLockup />     — manga + "mangaba.ai" empilhados (login, landing)
//   <BrandLockup row /> — manga + wordmark lado a lado (cabeçalhos largos)

export function BrandMark({
  size = 28,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <img
      src={markUrl}
      srcSet={`${markUrl} 1x, ${mark2xUrl} 2x`}
      alt=""
      aria-hidden
      className={"brand-mark-img " + className}
      // A arte é mais alta que larga; fixar só a altura preserva a proporção em
      // qualquer tamanho sem o CSS ter que saber o aspecto.
      style={{ height: size, width: "auto" }}
      draggable={false}
    />
  );
}

export function BrandWordmark({
  height = 22,
  className = "",
}: {
  height?: number;
  className?: string;
}) {
  return (
    <picture>
      {/* O tema escuro do app é dirigido por data-theme; o media query cobre o
          "auto" (preferência do sistema) — as duas rotas levam à arte clara. */}
      <source srcSet={wordmarkDarkUrl} media="(prefers-color-scheme: dark)" />
      <img
        src={wordmarkUrl}
        alt="mangaba.ai"
        className={"brand-wordmark-img " + className}
        style={{ height, width: "auto" }}
        draggable={false}
      />
    </picture>
  );
}

export function BrandLockup({
  size = 56,
  row = false,
  className = "",
}: {
  size?: number;
  row?: boolean;
  className?: string;
}) {
  return (
    <div className={`brand-lockup${row ? " row" : ""} ${className}`}>
      <BrandMark size={size} />
      <BrandWordmark height={row ? size * 0.42 : size * 0.52} />
    </div>
  );
}
