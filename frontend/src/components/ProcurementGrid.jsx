/**
 * ProcurementGrid.jsx  -  THE DASHBOARD (AG Grid)
 * ================================================
 *
 * WHAT THIS DOES
 *   Shows a live table ("Procurement Log") of every order the AI creates.
 *   Columns: Order ID, Timestamp, Item Name, Total Price,
 *            PayPal Transaction ID, Status.
 *
 * HOW IT STAYS "LIVE"
 *   Every 3 seconds it asks the backend for /api/orders and updates the
 *   table. So you can watch an order go from "Pending Authorization" to
 *   "Payment Captured" to "Execution Complete".
 *
 * WHAT IS AG GRID?
 *   A very powerful table component: sorting, filtering, resizing columns...
 *   We only describe the COLUMNS and give it the ROWS. It does the rest.
 */
import { useEffect, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";
import confetti from "canvas-confetti"; // a tiny library that draws confetti

// AG Grid v33+ needs you to switch on its features once. This turns on all
// the free ones (sorting, filtering, etc.).
ModuleRegistry.registerModules([AllCommunityModule]);

// Empty = "same address as this page" (works with Vite's proxy and with Docker/nginx).
// For a separate frontend host set VITE_API_URL when building.
const API_URL = import.meta.env.VITE_API_URL || "";

// PARTY POPPER: two confetti cannons fire from the bottom corners, three times.
// (Skipped if the person's computer is set to "reduce motion".)
function partyPopper() {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const shoot = () => {
    confetti({ particleCount: 70, angle: 60, spread: 70, startVelocity: 55, origin: { x: 0, y: 1 } });
    confetti({ particleCount: 70, angle: 120, spread: 70, startVelocity: 55, origin: { x: 1, y: 1 } });
  };
  shoot();
  setTimeout(shoot, 300);
  setTimeout(shoot, 700);
}

// Nice labels and colours for each status. The keys match the backend.
const STATUS_LOOK = {
  pending_authorization: { label: "Pending Authorization", bg: "#fff4d6", color: "#8a5a00" },
  payment_captured: { label: "Payment Captured", bg: "#dbeafe", color: "#1e40af" },
  executing: { label: "Executing Checkout", bg: "#ede9fe", color: "#5b21b6" },
  execution_complete: { label: "Execution Complete", bg: "#dcfce7", color: "#166534" },
  failed: { label: "Failed", bg: "#fee2e2", color: "#991b1b" },
};

// A "cell renderer" is a small component that draws ONE cell.
// This one draws the status as a coloured badge.
function StatusBadge(props) {
  const look = STATUS_LOOK[props.value] || { label: props.value, bg: "#eee", color: "#333" };
  return (
    <span
      style={{
        background: look.bg,
        color: look.color,
        padding: "2px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
      }}
    >
      {look.label}
    </span>
  );
}

// For unpaid orders, show a link that opens the PayPal approval page.
function ApproveLink(props) {
  if (props.data.status !== "pending_authorization") return null;
  return (
    <a href={props.data.approval_url} target="_blank" rel="noreferrer">
      Approve on PayPal
    </a>
  );
}

// The picture of the item being bought.
function ItemImage(props) {
  if (!props.value) return <span style={{ color: "#aaa" }}>—</span>;
  return (
    <img
      src={props.value}
      alt=""
      referrerPolicy="no-referrer"
      style={{ height: 52, width: 52, objectFit: "contain", borderRadius: 6, background: "#fff", display: "block", margin: "5px auto" }}
    />
  );
}

// The columns. Each object describes one column.
//   field      = which key of the order to show
//   headerName = the title at the top
const columns = [
  { field: "image_url", headerName: "Image", width: 90, sortable: false, filter: false, cellRenderer: ItemImage },
  { field: "order_id", headerName: "Order ID", width: 140 },
  {
    field: "created_at",
    headerName: "Timestamp",
    width: 200,
    sort: "desc", // newest first
    // The backend sends a machine-style time; show it in a friendly way.
    valueFormatter: (p) => (p.value ? new Date(p.value).toLocaleString() : ""),
  },
  { field: "item_name", headerName: "Item Name", flex: 2, minWidth: 220 },
  {
    field: "total_price",
    headerName: "Total Price",
    width: 130,
    valueFormatter: (p) => (p.value == null ? "" : `$${Number(p.value).toFixed(2)}`),
  },
  {
    field: "paypal_transaction_id",
    headerName: "PayPal Transaction ID",
    width: 220,
    // Before payment there is no id yet, so show a dash.
    valueFormatter: (p) => p.value || "—",
  },
  { field: "status", headerName: "Status", width: 200, cellRenderer: StatusBadge },
  { headerName: "Action", width: 170, sortable: false, filter: false, cellRenderer: ApproveLink },
  // wrapText + autoHeight make long notes (like error reasons) wrap onto several lines.
  { field: "detail", headerName: "Notes", flex: 2, minWidth: 320, wrapText: true, autoHeight: true },
];

export default function ProcurementGrid() {
  // "rows" holds the orders. "setRows" updates them (and redraws the table).
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");

  // We remember the last status of every order, so we can notice the moment
  // an order BECOMES complete. null = we haven't loaded anything yet.
  const lastStatus = useRef(null);

  // useEffect runs code when the component appears on screen.
  useEffect(() => {
    // Fetch the orders from the backend.
    async function loadOrders() {
      try {
        const response = await fetch(`${API_URL}/api/orders`);
        if (!response.ok) throw new Error(`Server said ${response.status}`);
        const orders = await response.json();

        if (lastStatus.current === null) {
          // First load: just remember what is already there (no confetti for old orders).
          lastStatus.current = {};
        } else {
          // Later loads: did any order just turn into "execution_complete"? Party time!
          for (const order of orders) {
            const before = lastStatus.current[order.order_id];
            if (order.status === "execution_complete" && before !== "execution_complete") {
              partyPopper();
              setBanner(`Order complete: ${order.item_name}`);
              setTimeout(() => setBanner(""), 7000);
            }
          }
        }
        for (const order of orders) lastStatus.current[order.order_id] = order.status;

        setRows(orders);
        setError("");
      } catch (e) {
        setError(e.message); // keep showing the old rows if the server blips
      }
    }

    loadOrders(); // once right away...
    const timer = setInterval(loadOrders, 3000); // ...then every 3 seconds

    // Cleanup: stop the timer when the component disappears.
    return () => clearInterval(timer);
  }, []); // [] = "only set this up once"

  return (
    <div style={{ padding: 16 }}>
      <h2>Procurement Log</h2>
      {error && <p style={{ color: "#b91c1c" }}>Can't reach the backend: {error}</p>}
      {banner && (
        <p
          role="status"
          style={{ background: "#dcfce7", color: "#166534", padding: "10px 16px", borderRadius: 10, fontWeight: 600 }}
        >
          🎉 {banner}
        </p>
      )}

      {/* AG Grid needs a fixed height to draw into. */}
      <div style={{ height: 480, width: "100%" }}>
        <AgGridReact
          rowData={rows}
          columnDefs={columns}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          // A stable id per row stops the table from flickering on refresh.
          rowHeight={64}
          getRowId={(params) => params.data.order_id}
          overlayNoRowsTemplate="No orders yet. Ask the agent to buy something!"
        />
      </div>
    </div>
  );
}
