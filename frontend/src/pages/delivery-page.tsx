import { Link, useParams } from "react-router-dom"
import { SingleDeliveryReceipt } from "@/components/delivery-receipts"

export default function DeliveryPage() {
  const { id } = useParams()
  return <div className="mx-auto w-full max-w-3xl space-y-6 p-4 sm:p-6">
    <Link to="/incidents" className="text-sm underline">Volver a las alertas</Link>
    <h1 className="text-2xl font-semibold">Recibo de envío</h1>
    {id && <SingleDeliveryReceipt deliveryId={id} />}
  </div>
}
