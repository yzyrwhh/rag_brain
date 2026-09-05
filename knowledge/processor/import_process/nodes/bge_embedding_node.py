import json
import os
from typing import List

from knowledge.processor.import_process.base import BaseNode, setup_logging
from knowledge.processor.import_process.config import get_config
from knowledge.processor.import_process.exceptions import EmbeddingError
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.utils.bge_client_util import get_bgem3_client
from knowledge.utils.normalize_sparse_vector import normalize_sparse_vector


class BgeEmbeddingNode(BaseNode):
    name = "bge_embedding"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        config = get_config()
        chunks = state.get("chunks", [])

        if not isinstance(chunks, list) or not chunks:
            raise EmbeddingError("chunks 为空或无效", node_name=self.name)

        self.log_step("step_1", f"开始为 {len(chunks)} 个切片生成向量")

        try:
            bge_m3_ef = get_bgem3_client()
        except Exception as e:
            raise EmbeddingError(f"初始化 BGE-M3 失败: {e}", node_name=self.name, cause=e)

        output_data = []
        batch_size = config.embedding_batch_size

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_output = self._process_batch(bge_m3_ef, batch, i, len(chunks))
            output_data.extend(batch_output)

        self.log_step("step_2", f"向量化完成，共 {len(output_data)} 个切片")
        state["chunks"] = output_data
        return state

    def _process_batch(
                self,
                bge_m3_ef,
                batch: List[dict],
                start_idx: int,
                total: int
        ) -> List[dict]:
            try:
                # 构造输入文本：item_name + content
                texts = [
                    (doc.get("item_name", "") or "") + "\n" + (doc.get("content", "") or "")
                    for doc in batch
                ]

                embeddings = bge_m3_ef.encode_documents(texts)

                if not embeddings:
                    self.logger.warning(f"批次 {start_idx + 1}-{start_idx + len(batch)} 未能生成向量")
                    return batch

                output = []
                for j, doc in enumerate(batch):
                    dense = embeddings["dense"][j]
                    dense_vector = dense.tolist() if hasattr(dense, 'tolist') else dense

                    sparse_list = embeddings["sparse"]  # 预期为列表，每个元素是字典 {token_id: weight}
                    if isinstance(sparse_list, list) and j < len(sparse_list):
                        sparse_dict = sparse_list[j] if sparse_list[j] is not None else {}
                    else:
                        sparse_dict = {}
                    sparse_vector = normalize_sparse_vector(sparse_dict)  # 归一化处理

                    # ----- 构建输出（字段与原来完全一致）-----
                    item = {
                        "content": doc.get("content"),
                        "title": doc.get("title"),
                        "parent_title": doc.get("parent_title", ""),
                        "part": doc.get("part", 0),
                        "file_title": doc.get("file_title"),
                        "item_name": doc.get("item_name"),
                        "dense_vector": dense_vector,
                        "sparse_vector": sparse_vector
                    }
                    output.append(item)
                self.logger.info(
                        f"成功处理批次 {start_idx + 1}-{min(start_idx + len(batch), total)}/{total}"
                )
                return output
            except Exception as e:
                self.logger.error(
                    f"批次 {start_idx + 1}-{start_idx + len(batch)} 处理失败: {e}"
                )
            # 返回原始数据，不含向量
            return batch

node_bge_embedding = BgeEmbeddingNode()

if __name__ == '__main__':
    """
    独立测试 BgeEmbeddingNode

    测试流程：
    1. 直接构造包含 item_name 的 state（不依赖外部文件）
    2. 执行向量化处理
    3. 将结果保存到指定路径
    4. 验证输出数据结构
    """

    setup_logging()

    # ----------------------------------------------------------------
    # Step 1: 配置输出路径
    # ----------------------------------------------------------------
    # 改为你指定的输出目录（请确保该目录存在，或者程序会自动创建？这里不处理创建）
    output_dir = r"examples/out"
    # 输出文件名沿用原逻辑
    output_path = os.path.join(output_dir, "chunks_item_name_vector.json")

    # ----------------------------------------------------------------
    # Step 2: 直接构造测试 state（完全硬编码，来自你提供的数据）
    # ----------------------------------------------------------------
    state = {
        "file_title": "6W100-整本手册",
        "chunks": [
            {
                "title": "",
                "content": "\n\nH3C LA2608 室内无线网关\n\n用户手册\n\nCopyright © 2014 杭州华三通信技术有限公司及其许可者 版权所有，保留一切权利。\n\n未经本公司书面许可，任何单位和个人不得擅自摘抄、复制本书内容的部分或全部，并不得以任何形式传播。\n\nH3C、 、Aolynk、 、H<sup>3</sup>Care、 、TOP G、 TOPG IRF、NetPilot、Neocean、NeoVTL、SecPro、SecPoint、SecEngine、SecPath、Comware、Secware、Storware、NQA、VVG、V<sup>2</sup>G、V<sup>n</sup>G、PSPT、XGbus、N-Bus、TiGem、InnoVision、HUASAN、华三均为杭州华三通信技术有限公司的商标。对于本手册中出现的其它公司的商标、产品标识及商品名称，由各自权利人拥有。\n\n由于产品版本升级或其他原因，本手册内容有可能变更。H3C保留在没有任何通知或者提示的情况下对本手册的内容进行修改的权利。本手册仅作为使用指导，H3C尽全力在本手册中提供准确的信息，但是 H3C 并不确保手册内容完全没有错误，本手册中的所有陈述、信息和建议也不构成任何明示或暗示的担保。\n",
                "file_title": "6W100-整本手册",
                "parent_title": "6W100-整本手册",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## 目 录",
                "content": "## 目 录\n\n\n1 H3C LA2608 室内无线网关用户手册 ····· ·······································································  \n1.1 概述 ········· ··································································································· 1  \n1.2 配置LA2608 与无线控制器互通 ············································································································ 1  \n1.2.1 配置LA2608 ········· ··········································································································· 1  \n1.2.2 配置运营商无线控制器 ·············································································································· 2  \n1.2.3 验证LA2608 与无线控制器是否连通 ·························································································· 3\n",
                "file_title": "6W100-整本手册",
                "parent_title": "## 目 录",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## 1 H3C LA2608 室内无线网关用户手册",
                "content": "## 1 H3C LA2608 室内无线网关用户手册\n\n",
                "file_title": "6W100-整本手册",
                "parent_title": "## 1 H3C LA2608 室内无线网关用户手册",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## 1.1 概述",
                "content": "## 1.1 概述\n\n\nH3C LA2608-GM/GU 室内无线网关（以下简称 LA2608）可以为用户提供无线服务，为了实现对设备的管理，LA2608需要通过 3G/4G网络连接到运营商无线控制器。\n\n![](images/df229fcb5e3b222c3e04ab69084b325f0e67f1de80f7d4e78b7826b543232f5d.jpg)\n\n说明\n\n目前，LA2608只支持与 H3C公司的无线控制器互通。\n",
                "file_title": "6W100-整本手册",
                "parent_title": "## 1.1 概述",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## 1.2 配置LA2608与无线控制器互通",
                "content": "## 1.2 配置LA2608与无线控制器互通\n\n\n如 图 1 所示，LA2608 安装了SIM卡，通过 3G/4G网络连接到运营商无线控制器，并向用户提供无线服务。关于LA2608的安装方法，请参见“H3C LA2608室内无线网关 快速安装指南”。\n\n图1 配置 LA2608与无线控制器互通\n\n![](images/4ccee3c380f5b5eebb16634b6395a8bb9bfc14476278ece11f5321e85f98b226.jpg)\n",
                "file_title": "6W100-整本手册",
                "parent_title": "## 1.2 配置LA2608与无线控制器互通",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## 1.2.1 配置LA2608",
                "content": "## 1.2.1 配置LA2608\n\n\n(1) 配置拨号访问组的拨号控制列表\n\n<LA2608>system-view  \n[LA2608]dialer-rule 1 ip permit  \n(2) 配置 DCC 拨号\n\n![](images/957b37753e127740347a1fc8cca1d3cd84d54a55ed1d249fc14ae43def77c1c4.jpg)\n\ndialer number命令用来配置发起呼叫的拨号串，不同运营商的拨号串不同，请用户在配置前向网络运营商获取发起呼叫的拨号串。\n\n[LA2608]interface Cellular-Ethernet2/0   \n[LA2608-Cellular-Ethernet2/0]ip address cellular-allocated   \n[LA2608-Cellular-Ethernet2/0]dialer enable-circular   \n[LA2608-Cellular-Ethernet2/0]dialer-group 1   \n[LA2608-Cellular-Ethernet2/0]dialer timer idle 0\n\n[LA2608-Cellular-Ethernet2/0]dialer timer autodial 5   \n[LA2608-Cellular-Ethernet2/0]dialer number \\*99# autodial   \n[LA2608-Cellular-Ethernet2/0]nat outbound   \n[LA2608-Cellular-Ethernet2/0]quit   \n(3) 配置 DNS 解析功能   \n[LA2608]dns resolve   \n(4) 配置静态路由   \n[LA2608]ip route-static 0.0.0.0 0.0.0.0 Cellular-Ethernet2/0   \n(5) 指定运营商无线控制器的 IP地址   \n[LA2608] wlan ac ip 60.191.99.143\n",
                "file_title": "6W100-整本手册",
                "parent_title": "## 1.2.1 配置LA2608",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## 1.2.2 配置运营商无线控制器",
                "content": "## 1.2.2 配置运营商无线控制器\n\n\n![](images/8c3789bec91cf0b1bfc1305e07efb6be5d28185d9627bddda68d86ab6718de9b.jpg)\n",
                "file_title": "6W100-整本手册",
                "parent_title": "## 1.2.2 配置运营商无线控制器",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## 说明",
                "content": "## 说明\n\n\n如下配置仅供参考，运营商可根据实际情况进行调整。\n",
                "file_title": "6W100-整本手册",
                "parent_title": "## 说明",
                "item_name": "H3C LA2608 室内无线网关"
            },
            {
                "title": "## (1) 创建业务 VLAN (1) 创建业务 VLAN",
                "content": "## (1) 创建业务 VLAN (1) 创建业务 VLAN\n\n\n<AC>system-view  \n[AC]vlan 2  \n[AC-vlan2] quit  \n(2) 创建 WLAN-ESS 接口并加入业务 VLAN  \n[AC]interface WLAN-ESS 1  \n[AC-WLAN-ESS1]port access vlan 2  \n[AC-WLAN-ESS1]quit  \n(3) 配置明文方式的服务模板  \n[AC]wlan service-template 1 clear  \n[AC-wlan-st-1]ssid ssidh3c  \n[AC-wlan-st-1]bind WLAN-ESS 1  \n[AC-wlan-st-1]service-template enable  \nPlease wait... Done.  \n[AC-wlan-st-1]quit  \n(4) 开启自动 AP 功能  \n[AC]wlan auto-ap enable  \n[AC]wlan ap 2608 model LA2608 id 1  \n[AC-wlan-ap-2608]serial-id auto  \n[AC-wlan-ap-2608]radio 1  \n[AC-wlan-ap-2608-radio-1]service-template 1  \n[AC-wlan-ap-2608-radio-1]radio enable  \n[AC-wlan-ap-2608-radio-1]quit  \n[AC-wlan-ap-2608]quit  \n(5) 配置 VLAN 接口 IP 地址  \n[AC]interface Vlan-interface 1  \n[AC-Vlan-interface1]ip address 60.191.99.143 255.255.0.0  \n[AC-Vlan-interface1]quit  \n[AC]interface Vlan-interface 2  \n[AC-Vlan-interface2]ip address 10.249.136.1 255.255.252.0  \n[AC-Vlan-interface2]quit  \n(6) 使能 DHCP 服务，配置 DHCP 地址池\n\n```ini\n[AC]dhcp enable\n[AC]dhcp server ip-pool vlan2\n[AC-dhcp-pool-vlan1]network 10.249.136.0 22\n[AC-dhcp-pool-vlan1]gateway-list 10.249.136.1\n[AC-dhcp-pool-vlan1]dns-list 218.201.96.130\n[AC-dhcp-pool-vlan1]quit\n```\n\n## 1.2.3 验证LA2608 与无线控制器是否连通\n\n在无线控制器上执行 display wlan ap 命令，state 字段显示为“R/M”，表示 LA2608 与无线控制器之间已经建立连接。\n\n<Sysname> display wlan ap all   \nTotal Number of APs configured : 1   \nTotal Number of configured APs connected : 1   \nTotal Number of auto APs connected : 0   \nAP Profiles   \nState : I = Idle, J = Join, JA = JoinAck, IL = ImageLoad   \nC = Config, R = Run, KU = KeyUpdate, KC = KeyCfm   \nM = Master, B = Backup   \nAP Name State Model Serial-ID   \nap1 R/M LA2608 036286A054000033",
                "file_title": "6W100-整本手册",
                "parent_title": "## (1) 创建业务 VLAN (1) 创建业务 VLAN",
                "item_name": "H3C LA2608 室内无线网关"
            }
        ],
        "item_name": "H3C LA2608 室内无线网关"
    }

    print(f"已构造测试 state，包含 {len(state['chunks'])} 个切片")

    # ----------------------------------------------------------------
    # Step 3: 构建状态并执行处理（直接使用上面的 state）
    # ----------------------------------------------------------------
    print("开始执行向量化...")
    result = node_bge_embedding.process(state)

    # ----------------------------------------------------------------
    # Step 4: 验证输出数据（完全保留原有验证逻辑）
    # ----------------------------------------------------------------
    output_chunks = result.get("chunks", [])
    print(f"\n处理完成，共 {len(output_chunks)} 个切片")

    # 检查第一个切片的向量
    if output_chunks:
        first_chunk = output_chunks[0]

        print("\n第一个切片数据结构:")
        print(f"  - content: {first_chunk.get('content', '')[:50]}...")
        print(f"  - title: {first_chunk.get('title', '')}")
        print(f"  - item_name: {first_chunk.get('item_name', '')}")

        dense_vec = first_chunk.get('dense_vector', [])
        sparse_vec = first_chunk.get('sparse_vector', {})

        print(f"\n向量信息:")
        print(f"  - dense_vector 维度: {len(dense_vec)}")
        print(f"  - dense_vector 前5维: {dense_vec[:5] if dense_vec else '无'}")
        print(f"  - sparse_vector 非零元素数: {len(sparse_vec)}")
        print(f"  - sparse_vector 前3项: {dict(list(sparse_vec.items())[:3]) if sparse_vec else '无'}")

        # 验证稀疏向量是否已归一化
        if sparse_vec:
            import numpy as np
            values = np.array(list(sparse_vec.values()))
            l2_norm = np.linalg.norm(values)
            print(f"  - sparse_vector L2范数: {l2_norm:.6f} (归一化后应接近1.0)")

    # ----------------------------------------------------------------
    # Step 5: 保存输出文件（使用新路径）
    # ----------------------------------------------------------------
    # 确保输出目录存在（如果不存在则创建）
    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"\n已保存到: {output_path}")
