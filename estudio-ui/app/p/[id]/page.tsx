import Proyecto from "@/components/Proyecto";

export default async function Pagina({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Proyecto id={id} />;
}
