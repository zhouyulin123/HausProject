import { lazy, Suspense, type ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";
import Layout from "@/components/layout/Layout";
import RouteErrorPage from "@/components/common/RouteErrorPage";
import {
  RequireAdmin,
  RequireAuth,
  RequireFactory,
} from "@/components/auth/RouteGuard";
import HomePage from "@/pages/HomePage";
import { importWithRetry } from "@/lib/lazyImport";
import { DESIGN_START_PATH } from "@/lib/designWorkspaceRouting";

type PageModule = { default: ComponentType };
const lazyPage = (importer: () => Promise<PageModule>) =>
  lazy(() => importWithRetry(importer));

const CustomizePage = lazyPage(() => import("@/pages/CustomizePage"));
const UploadPage = lazyPage(() => import("@/pages/UploadPage"));
const ChatPage = lazyPage(() => import("@/pages/ChatPage"));
const ResultsPage = lazyPage(() => import("@/pages/ResultsPage"));
const DesignDetailPage = lazyPage(() => import("@/pages/DesignDetailPage"));
const DesignStartPage = lazyPage(() => import("@/pages/DesignStartPage"));
const DesignWorkspacePage = lazyPage(
  () => import("@/pages/DesignWorkspacePage"),
);
const FurniturePage = lazyPage(() => import("@/pages/FurniturePage"));
const StyleGalleryPage = lazyPage(() => import("@/pages/StyleGalleryPage"));
const MyDesignsPage = lazyPage(() => import("@/pages/MyDesignsPage"));
const OrdersPage = lazyPage(() => import("@/pages/OrdersPage"));
const WorkspacePage = lazyPage(() => import("@/pages/WorkspacePage"));
const CustomersPage = lazyPage(() => import("@/pages/CustomersPage"));
const AdminPage = lazyPage(() => import("@/pages/AdminPage"));
const AdminUsersPage = lazyPage(() => import("@/pages/AdminUsersPage"));
const AdminQualityPage = lazyPage(() => import("@/pages/AdminQualityPage"));
const LoginPage = lazyPage(() => import("@/pages/LoginPage"));
const Demo3DPage = lazyPage(() => import("@/pages/Demo3DPage"));

export const router = createBrowserRouter(
  [
    {
      path: "/demo",
      errorElement: <RouteErrorPage />,
      element: (
        <Suspense
          fallback={
            <div className="flex h-screen items-center justify-center bg-[#E7DECF] text-sm text-stone-500">
              正在加载 3D 演示…
            </div>
          }
        >
          <Demo3DPage />
        </Suspense>
      ),
    },
    {
      path: "/",
      element: <Layout />,
      errorElement: <RouteErrorPage />,
      children: [
        { index: true, element: <HomePage /> },
        { path: "customize", element: <CustomizePage /> },
        { path: "upload", element: <UploadPage /> },
        { path: "chat", element: <ChatPage /> },
        { path: "results", element: <ResultsPage /> },
        { path: DESIGN_START_PATH.slice(1), element: <DesignStartPage /> },
        {
          path: "design/:projectId/workspace",
          element: <DesignWorkspacePage />,
        },
        { path: "design/:id", element: <DesignDetailPage /> },
        { path: "furniture", element: <FurniturePage /> },
        { path: "styles", element: <StyleGalleryPage /> },
        { path: "my-designs", element: <MyDesignsPage /> },
        {
          path: "orders",
          element: (
            <RequireAuth>
              <OrdersPage />
            </RequireAuth>
          ),
        },
        {
          path: "workspace",
          element: (
            <RequireFactory>
              <WorkspacePage />
            </RequireFactory>
          ),
        },
        {
          path: "customers",
          element: (
            <RequireFactory>
              <CustomersPage />
            </RequireFactory>
          ),
        },
        {
          path: "admin",
          element: (
            <RequireFactory>
              <AdminPage />
            </RequireFactory>
          ),
        },
        {
          path: "admin/users",
          element: (
            <RequireAdmin>
              <AdminUsersPage />
            </RequireAdmin>
          ),
        },
        {
          path: "admin/quality",
          element: (
            <RequireAdmin>
              <AdminQualityPage />
            </RequireAdmin>
          ),
        },
        { path: "login", element: <LoginPage /> },
      ],
    },
  ],
  {
    future: {
      v7_relativeSplatPath: true,
    },
  },
);
