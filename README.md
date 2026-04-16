# GitOps Engine

GitOps Engine là một khung làm việc (framework) được thiết kế để quản lý Helm Monorepo ở quy mô lớn. Hệ thống sử dụng cơ chế tổng hợp cấu hình dựa trên Python để trừu tượng hóa sự phức tạp của Kubernetes, tối ưu hóa luồng công việc GitOps và đảm bảo đồng bộ hóa secret an toàn thông qua HashiCorp Vault.

## Tổng quan hệ thống

GitOps Engine tập trung quản lý ứng dụng vào một nguồn dữ liệu tin cậy duy nhất (Single Source of Truth), loại bỏ tình trạng sai lệch cấu hình và giảm thiểu chi phí vận hành.

*   Tổng hợp dựa trên logic: Sử dụng bộ sinh cấu hình Python để suy luận các tài nguyên Kubernetes từ các khai báo cấp cao.
*   Ghi ngược tự động (Write-back): Pipeline CI tự động cập nhật manifest và commit thay đổi ngược lại repository để lưu vết kiểm thử (audit trail).
*   Tích hợp bảo mật: Secret được quản lý bên ngoài tại Vault và đồng bộ trực tiếp vào cluster, đảm bảo không có dữ liệu nhạy cảm nào lưu trữ trong Git.

## Cấu trúc dự án

| Thành phần | Vai trò |
| :--- | :--- |
| argocd/ | Manifest ApplicationSet phục vụ việc tự động phát hiện dịch vụ. |
| helm-templates/ | Library Chart (common-lib) chứa các template Kubernetes chuẩn hóa. |
| projects/ | Thư mục chứa cấu hình riêng cho từng dự án (ví dụ: ecommerce). |
| scripts/ | Các công cụ tự động hóa cốt lõi: deploy.sh, generator.py và vault_sync.sh. |
| examples/ | Các mẫu pipeline CI/CD cho GitLab và GitHub. |

## Quy ước cấu hình

Hệ thống sử dụng cách tiếp cận khai báo thông qua apps.yaml để định nghĩa trạng thái ứng dụng.

### Logic suy luận (Inference Logic)

Script generator.py áp dụng các quy tắc suy luận để giảm thiểu việc cấu hình thủ công:

| Tính năng | Logic suy luận |
| :--- | :--- |
| Image Registry | Mặc định là registry/project-name/app-name:latest nếu không chỉ định. |
| Khởi tạo Service | Tự động khởi tạo nếu phát hiện khối cấu hình port hoặc ingress. |
| Ánh xạ Port | Ánh xạ service.port tới containerPort. Mặc định là 80 nếu không định nghĩa. |
| Health Checks | Mặc định là HTTP check tại đường dẫn / nếu được kích hoạt. Tự động chuyển sang TCP Socket nếu không có path. |
| Lưu trữ (PVC) | Tự động sinh PersistentVolumeClaim và VolumeMounts nếu pvc.mountPath được định nghĩa. |
| Ingress Hosts | Chuyển đổi các khai báo host đơn giản thành manifest ingress chuẩn. |

## Luồng vận hành

### Thực thi tại địa phương (Local)
Để sinh manifest tại địa phương nhằm mục đích kiểm tra:
```bash
python3 scripts/generator.py --project <tên_dự án> --env <môi_trường> [--dry-run]
```

### Điều phối CI/CD
Quá trình triển khai được xử lý bởi scripts/deploy.sh trong môi trường CI:
1.  Sinh Manifest: Thực thi bộ sinh với mã định danh pipeline CI làm image tag bất biến.
2.  Phát hiện thay đổi: Kiểm tra xem manifest mới có khác biệt so với trạng thái hiện tại hay không.
3.  Commit nguyên tử: Thực hiện commit và đẩy ngược (push-back) thay đổi về repository.
4.  Kiểm soát đồng thời: Sử dụng cơ chế khóa resource_group và logic retry-rebase để xử lý an toàn các pipeline thực thi đồng thời.

## Tích hợp GitOps

Framework tận dụng ArgoCD ApplicationSet với Git Generator để quản lý vòng đời dịch vụ tự động:

1.  Giám sát thư mục: ArgoCD giám sát các đường dẫn projects/*/charts/.
2.  Tự động phát hiện: Các thư mục con mới được tự động khởi tạo thành các Ứng dụng ArgoCD độc lập.
3.  Phân loại trực quan: Các ứng dụng được gắn nhãn và phân bổ vào các Dự án ArgoCD riêng biệt để cách ly và quản lý nhóm trên giao diện người dùng.

## Quản lý Secret

Công cụ đồng bộ hóa (vault_sync.sh) hỗ trợ hai đối tượng chính:
*   Kubernetes (Chế độ: k8s): Đồng bộ trực tiếp từ Vault KV-v2 sang K8s Secrets.
*   Máy ảo (Chế độ: vm): Logic nạp dữ liệu (upsert) cho các file .env tại địa phương với cơ chế chống trùng lặp.

Cách sử dụng:
```bash
./scripts/vault_sync.sh <đường_dẫn_vault> <tên_secret> <namespace>
./scripts/vault_sync.sh vm <đường_dẫn_vault> <đường_dẫn_file_env>
```
