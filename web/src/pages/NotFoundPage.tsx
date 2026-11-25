import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="empty">
      <h1>Página no encontrada</h1>
      <p>
        <Link to="/">Volver a tus partidas</Link>
      </p>
    </section>
  );
}
