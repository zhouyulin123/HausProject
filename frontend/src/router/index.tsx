import { createBrowserRouter } from "react-router-dom";
import Layout from "@/components/layout/Layout";
import HomePage from "@/pages/HomePage";
import CustomizePage from "@/pages/CustomizePage";
import UploadPage from "@/pages/UploadPage";
import ChatPage from "@/pages/ChatPage";
import ResultsPage from "@/pages/ResultsPage";
import DesignDetailPage from "@/pages/DesignDetailPage";
import FurniturePage from "@/pages/FurniturePage";
import StyleGalleryPage from "@/pages/StyleGalleryPage";
import MyDesignsPage from "@/pages/MyDesignsPage";
import CustomersPage from "@/pages/CustomersPage";
import AdminPage from "@/pages/AdminPage";
import LoginPage from "@/pages/LoginPage";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <Layout />,
      children: [
        { index: true, element: <HomePage /> },
        { path: "customize", element: <CustomizePage /> },
        { path: "upload", element: <UploadPage /> },
        { path: "chat", element: <ChatPage /> },
        { path: "results", element: <ResultsPage /> },
        { path: "design/:id", element: <DesignDetailPage /> },
        { path: "furniture", element: <FurniturePage /> },
        { path: "styles", element: <StyleGalleryPage /> },
        { path: "my-designs", element: <MyDesignsPage /> },
        { path: "customers", element: <CustomersPage /> },
        { path: "admin", element: <AdminPage /> },
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
