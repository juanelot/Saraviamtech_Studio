import EstudioClips from "@/components/EstudioClips";

export default async function Pagina({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EstudioClips id={id} />;
}
