import { Router, type IRouter } from "express";
import healthRouter from "./health";
import { proxyToPython } from "./proxy";

const router: IRouter = Router();

// Health check — handled locally, not proxied
router.use(healthRouter);

// All other /api/* routes are forwarded to the DAWA Python backend
// (localhost:8000 by default, override via DAWA_BACKEND_URL)
router.use(proxyToPython);

export default router;
