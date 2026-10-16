// C# 5 / CLR4 API subset. Compiled against local 4.8 runtime references, NOT NT6.3-certified.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32;

internal static class FixedComHost
{
    const string Root = @"D:\CRM-ESCHF-001-Isolated";
    const string Target = Root + @"\ka_eschf_test";
    const string Image = Root + @"\runtime\eschf-probe.exe";
    const string Dll = @"C:\Program Files\1cv8\8.3.18.1661\bin\comcntr.dll";
    const string Marker = "CRM-ESCHF-001/4a4204e1-bad8-4f37-854a-f0b1495f8b61";
    const string Module = "CRMЭСЧФИзолированныйТест";
    const string Configuration = "КомплекснаяАвтоматизацияДляБеларуси";
    const string Kind = "CRM-ESCHF-001/P2/fixed-host-context-probe-v1";
    const uint JobFlags = 0x00000008 | 0x00000100 | 0x00002000; // active limit, process memory, kill on close
    static bool NativeActivationAttempted = false;
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 65536, RecursionLimit = 16 };
    static string Self { get { return Assembly.GetExecutingAssembly().Location; } }

    static Dictionary<string, object> Map(params object[] pairs)
    {
        var value = new Dictionary<string, object>(StringComparer.Ordinal);
        for (int i = 0; i < pairs.Length; i += 2) value.Add((string)pairs[i], pairs[i + 1]);
        return value;
    }
    static void Require(bool value, string code) { if (!value) throw new InvalidOperationException(code); }
    static string Text(Dictionary<string, object> map, string key)
    {
        object value; Require(map.TryGetValue(key, out value) && value is string && ((string)value).Length > 0, "missing_" + key);
        return (string)value;
    }
    static Dictionary<string, object> Object(Dictionary<string, object> map, string key)
    {
        object value; Require(map.TryGetValue(key, out value) && value is Dictionary<string, object>, "object_" + key);
        return (Dictionary<string, object>)value;
    }
    static bool Flag(Dictionary<string, object> map, string key)
    { object value; return map.TryGetValue(key, out value) && value is bool && (bool)value; }
    static string Hash(byte[] bytes)
    { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
    static string FileHash(string path)
    { using (var sha = SHA256.Create()) using (var stream = File.OpenRead(path)) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant(); }
    static bool IsHash(string text) { return text != null && Regex.IsMatch(text, @"\A[0-9a-f]{64}\z"); }
    static byte[] ReadBounded(string path)
    {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            Require(stream.Length <= 65536, "json_size");
            byte[] raw = new byte[(int)stream.Length]; int offset = 0;
            while (offset < raw.Length) { int read = stream.Read(raw, offset, raw.Length - offset); Require(read > 0, "json_short_read"); offset += read; }
            return raw;
        }
    }
    static Dictionary<string, object> ReadJson(string path, string hash)
    {
        Require(IsHash(hash), "expected_hash_required"); NoReparse(path);
        byte[] raw = ReadBounded(path); Require(Hash(raw) == hash, "json_hash");
        string text = Utf8.GetString(raw); if (text.Length > 0 && text[0] == '\uFEFF') text = text.Substring(1);
        var result = Json.DeserializeObject(text) as Dictionary<string, object>;
        Require(result != null, "json_object"); return result;
    }
    static void NoReparse(string path)
    {
        Require(Path.IsPathRooted(path) && Path.GetFullPath(path) == path && path.IndexOfAny(new[] {'"', '\r', '\n'}) < 0, "absolute_path");
        string cursor = path;
        while (!String.IsNullOrEmpty(cursor))
        { Require((File.GetAttributes(cursor) & FileAttributes.ReparsePoint) == 0, "reparse_path"); cursor = Path.GetDirectoryName(cursor); }
    }
    static void StandPath(string path)
    { Require(path.StartsWith(Root + "\\", StringComparison.OrdinalIgnoreCase), "stand_path"); NoReparse(path); }
    static void WriteNew(string path, Dictionary<string, object> data)
    {
        byte[] raw = Utf8.GetBytes(Json.Serialize(data)); Require(raw.Length <= 65536, "result_size");
        using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) stream.Write(raw, 0, raw.Length);
    }

    static Dictionary<string, object> Approval(string path, string hash)
    {
        var a = ReadJson(path, hash);
        Require(Text(a, "kind") == Kind && Text(a, "target") == Target && Text(a, "host") == "1CSRV", "exact_p2_required");
        StandPath(Text(a, "source_approval_path"));
        var plan = ReadJson(Text(a, "source_approval_path"), Text(a, "source_approval_sha256"));
        Require(Text(plan, "kind") == "CRM-ESCHF-001/P2/approved-plan-v1" && Text(plan, "host") == "1CSRV" &&
            Text(plan, "target") == Target && Text(plan, "account_name") == @"1CSRV\CRM_ESCHF_Test" &&
            Text(plan, "worker_executable") == Image && Text(plan, "fixed_host_sha256") == Text(a, "worker_executable_sha256"), "source_approval_binding");
        Text(plan, "user_approval_reference"); // Established outside this program; never manufacture an approval.
        StandPath(Text(a, "account_receipt_path"));
        var account = ReadJson(Text(a, "account_receipt_path"), Text(a, "account_receipt_sha256"));
        Require(Text(account, "source_approval_sha256") == Text(a, "source_approval_sha256") &&
            Text(account, "account_name") == Text(plan, "account_name") && Text(account, "account_sid") == Text(a, "account_sid"), "account_setup_binding");
        Require(Environment.MachineName == "1CSRV" && IntPtr.Size == 8, "host_guard");
        using (var identity = WindowsIdentity.GetCurrent())
        {
            Require(identity.User.Value == Text(a, "account_sid"), "account_sid");
            Require(identity.User.Value != "S-1-5-18" && identity.User.Value != "S-1-5-19" && identity.User.Value != "S-1-5-20", "service_account");
            foreach (IdentityReference group in identity.Groups) Require(group.Value != "S-1-5-32-544", "admin_token");
        }
        Require(Text(a, "worker_executable") == Image && Self.Equals(Image, StringComparison.OrdinalIgnoreCase), "fixed_image");
        StandPath(Image); Require(FileHash(Image) == Text(a, "worker_executable_sha256"), "image_hash");
        StandPath(Text(a, "isolation_receipt_path"));
        var isolation = ReadJson(Text(a, "isolation_receipt_path"), Text(a, "isolation_receipt_sha256"));
        foreach (string key in new[] {"target", "account_sid", "worker_executable", "worker_executable_sha256"})
            Require(Text(isolation, key) == Text(a, key), "isolation_binding");
        Require(Text(isolation, "source_approval_sha256") == Text(a, "source_approval_sha256"), "isolation_plan_binding");
        Require(Flag(isolation, "initialization_in_scope"), "initialization_scope"); Text(isolation, "independent_review_reference");
        foreach (string key in new[] {"key_access_evidence", "egress_evidence", "child_process_evidence"})
        { var evidence = Object(isolation, key); StandPath(Text(evidence, "path")); ReadJson(Text(evidence, "path"), Text(evidence, "sha256")); }
        // These receipts require human review of the concrete seed/call paths; hashes are not an isolation proof.
        StandPath(Text(a, "manifest_path")); var manifest = ReadJson(Text(a, "manifest_path"), Text(a, "manifest_sha256"));
        Require(Text(manifest, "target") == Target && Text(manifest, "marker") == Marker &&
            Text(manifest, "configuration_name") == Configuration && Text(manifest, "configuration_version") == "2.4.14.182", "manifest_identity");
        Require(Text(Object(manifest, "fixed_host"), "sha256") == Text(a, "worker_executable_sha256"), "manifest_host");
        string packageRoot = Path.GetDirectoryName(Text(a, "manifest_path"));
        foreach (var file in Object(manifest, "files"))
        {
            Require(!Path.IsPathRooted(file.Key) && file.Key.IndexOf(':') < 0 && file.Key.IndexOf("..", StringComparison.Ordinal) < 0, "package_path");
            string artifact = Path.GetFullPath(Path.Combine(packageRoot, file.Key)); StandPath(artifact);
            Require(file.Value is string && IsHash((string)file.Value) && FileHash(artifact) == (string)file.Value, "artifact_hash");
        }
        StandPath(Target); StandPath(Target + @"\1Cv8.1CD"); StandPath(Text(a, "test_base_receipt_path"));
        var seed = ReadJson(Text(a, "test_base_receipt_path"), Text(a, "test_base_receipt_sha256"));
        Require(Text(seed, "target") == Target && Text(seed, "marker") == Marker &&
            Text(seed, "manifest_sha256") == Text(a, "manifest_sha256") && IsHash(Text(a, "seed_cf_sha256")) &&
            Text(seed, "seed_cf_sha256") == Text(a, "seed_cf_sha256") &&
            Text(seed, "source_approval_sha256") == Text(a, "source_approval_sha256"), "seed_receipt");
        return a;
    }

    [StructLayout(LayoutKind.Sequential)] struct BasicLimits
    { public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinWorking, MaxWorking; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling; }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters
    { public ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] struct Limits
    { public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct Startup
    { public uint Size; public string Reserved, Desktop, Title; public uint X, Y, Width, Height, XChars, YChars, Fill, Flags; public ushort Show, ReservedSize; public IntPtr ReservedPtr, StdIn, StdOut, StdErr; }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo
    { public IntPtr Process, Thread; public uint Pid, Tid; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr OpenJobObject(uint access, bool inherit, string name);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetInformationJobObject(IntPtr job, int info, ref Limits value, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool QueryInformationJobObject(IntPtr job, int info, out Limits value, uint size, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CreateProcess(string application, StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes, bool inherit, uint flags, IntPtr environment, string directory, ref Startup startup, out ProcessInfo process);
    [DllImport("kernel32.dll", SetLastError = true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")] static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);

    static void Win(bool result, string code)
    { if (!result) throw new InvalidOperationException(code + "_" + Marshal.GetLastWin32Error().ToString(CultureInfo.InvariantCulture)); }
    static string Quote(string path)
    { Require(path.IndexOfAny(new[] {'"', '\r', '\n'}) < 0 && !path.EndsWith("\\", StringComparison.Ordinal), "argv_path"); return "\"" + path + "\""; }
    static bool OutputBound(string directory)
    {
        string[] files = Directory.GetFiles(directory); if (files.Length > 8) return false;
        long size = 0; foreach (string file in files) size += new FileInfo(file).Length;
        return size <= 1048576;
    }
    static int Supervise(string evidenceParent, string approvalPath, string approvalHash, string syntheticCase)
    {
        NoReparse(evidenceParent); string nonce = Guid.NewGuid().ToString("N");
        string directory = Path.Combine(evidenceParent, "host-" + nonce);
        Require(!Directory.Exists(directory) && !File.Exists(directory), "new_evidence"); Directory.CreateDirectory(directory);
        long memory = syntheticCase == null ? 3221225472L : 134217728L;
        int deadline = syntheticCase == "hang" ? 2 : 60;
        var request = Map("approval_path", approvalPath, "approval_sha256", approvalHash,
            "supervisor_pid", Process.GetCurrentProcess().Id, "supervisor_start", Process.GetCurrentProcess().StartTime.ToUniversalTime().ToString("o"),
            "job", "Local\\CRM-ESCHF-001-" + nonce, "directory", directory, "memory", memory,
            "synthetic_case", syntheticCase, "host_sha256", FileHash(Self));
        string requestPath = Path.Combine(directory, "request.json"); WriteNew(requestPath, request);
        var receipt = Map("scope", syntheticCase == null ? "isolated_context_probe_only" : "synthetic_nonnative",
            "native_com_invoked", syntheticCase == null ? (object)null : false,
            "AC03", false, "complete", false, "cleanup_confirmed", false,
            "job_assigned_before_resume", false, "worker_pid", 0, "broker_boundary_verified", false);
        IntPtr job = IntPtr.Zero; ProcessInfo child = new ProcessInfo(); bool assigned = false; uint exit = 259;
        try
        {
            job = CreateJobObject(IntPtr.Zero, Text(request, "job")); Win(job != IntPtr.Zero, "create_job");
            var limits = new Limits(); limits.Basic.Flags = JobFlags; limits.Basic.Active = 1;
            limits.ProcessMemory = new UIntPtr((ulong)memory);
            Win(SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(Limits))), "set_job_limits");
            var startup = new Startup(); startup.Size = (uint)Marshal.SizeOf(typeof(Startup));
            string args = Quote(Self) + " --worker " + Quote(requestPath) + " --request-sha256 " + Hash(ReadBounded(requestPath));
            Win(CreateProcess(Self, new StringBuilder(args), IntPtr.Zero, IntPtr.Zero, false, 0x08000004, IntPtr.Zero, directory, ref startup, out child), "create_suspended");
            receipt["worker_pid"] = child.Pid;
            Win(AssignProcessToJobObject(job, child.Process), "assign_job"); assigned = true;
            receipt["job_assigned_before_resume"] = true;
            Require(ResumeThread(child.Thread) != UInt32.MaxValue, "resume_failed");
            var watch = Stopwatch.StartNew();
            while (WaitForSingleObject(child.Process, 100) == 258)
            { Require(watch.Elapsed.TotalSeconds <= deadline, "worker_deadline"); Require(OutputBound(directory), "output_limit"); }
            Win(GetExitCodeProcess(child.Process, out exit), "exit_code");
            Require(OutputBound(directory), "output_limit"); Require(exit == 0, "worker_exit");
            string resultPath = Path.Combine(directory, "worker.json");
            var result = ReadJson(resultPath, FileHash(resultPath));
            Require(!Flag(result, "AC03") && Text(result, "scope") == (syntheticCase == null ? "synthetic_message_probe_only" : "synthetic_nonnative"), "worker_scope");
            receipt["worker_result_sha256"] = FileHash(resultPath); receipt["result"] = result; receipt["complete"] = true;
            receipt["native_com_invoked"] = Flag(result, "native_com_invoked");
        }
        catch (Exception failure) { receipt["failure"] = failure is InvalidOperationException ? failure.Message : failure.GetType().Name; }
        finally
        {
            if (child.Process != IntPtr.Zero)
            {
                if (assigned) TerminateJobObject(job, 125); else TerminateProcess(child.Process, 125);
                receipt["cleanup_confirmed"] = WaitForSingleObject(child.Process, 5000) == 0;
                GetExitCodeProcess(child.Process, out exit); receipt["exit_code"] = exit;
            }
            if (child.Thread != IntPtr.Zero) CloseHandle(child.Thread);
            if (child.Process != IntPtr.Zero) CloseHandle(child.Process);
            if (job != IntPtr.Zero) CloseHandle(job);
        }
        receipt["complete"] = Flag(receipt, "complete") && Flag(receipt, "cleanup_confirmed");
        WriteNew(Path.Combine(directory, "receipt.json"), receipt);
        Console.WriteLine(Json.Serialize(Map("receipt", Path.Combine(directory, "receipt.json"), "complete", Flag(receipt, "complete"), "AC03", false)));
        return Flag(receipt, "complete") ? 0 : 1;
    }

    static int Worker(string path, string hash)
    {
        var request = ReadJson(path, hash); string directory = Text(request, "directory"); NoReparse(directory);
        Require(path == Path.Combine(directory, "request.json") && Regex.IsMatch(Path.GetFileName(directory), @"\Ahost-[0-9a-f]{32}\z"), "worker_path");
        Require(Text(request, "host_sha256") == FileHash(Self), "worker_hash");
        using (var parent = Process.GetProcessById(Convert.ToInt32(request["supervisor_pid"], CultureInfo.InvariantCulture)))
        { Require(parent.Id != Process.GetCurrentProcess().Id && !parent.HasExited && parent.StartTime.ToUniversalTime().ToString("o") == Text(request, "supervisor_start"), "supervisor_identity"); }
        IntPtr job = OpenJobObject(4, false, Text(request, "job")); Win(job != IntPtr.Zero, "open_job");
        try
        {
            bool member; Win(IsProcessInJob(GetCurrentProcess(), job, out member), "query_membership"); Require(member, "own_job_required");
            Limits limits; Win(QueryInformationJobObject(job, 9, out limits, (uint)Marshal.SizeOf(typeof(Limits)), IntPtr.Zero), "query_limits");
            Require(limits.Basic.Flags == JobFlags && limits.Basic.Active == 1 && limits.ProcessMemory.ToUInt64() == Convert.ToUInt64(request["memory"], CultureInfo.InvariantCulture), "exact_job_limits");
        }
        finally { CloseHandle(job); }
        Dictionary<string, object> result;
#if SYNTHETIC_BACKEND
        result = Synthetic(Text(request, "synthetic_case"), directory);
#else
        Require(request["synthetic_case"] == null && directory.StartsWith(Root + @"\evidence\", StringComparison.OrdinalIgnoreCase), "native_request");
        Require(Convert.ToInt64(request["memory"], CultureInfo.InvariantCulture) == 3221225472L, "native_memory_limit");
        var approval = Approval(Text(request, "approval_path"), Text(request, "approval_sha256"));
        result = NativeProbe(approval); // Initialization may run in Connect: all gates above precede activation.
#endif
        WriteNew(Path.Combine(directory, "worker.json"), result); return 0;
    }

#if SYNTHETIC_BACKEND
    static Dictionary<string, object> Synthetic(string scenario, string directory)
    {
        var result = Map("scope", "synthetic_nonnative", "native_com_invoked", false, "AC03", false, "scenario", scenario);
        if (scenario == "hang") Thread.Sleep(120000);
        else if (scenario == "output") { File.WriteAllBytes(Path.Combine(directory, "synthetic-output.bin"), new byte[2097152]); Thread.Sleep(120000); }
        else if (scenario == "memory")
        {
            var allocations = new List<byte[]>(); bool blocked = false;
            try { for (int i = 0; i < 512; i++) { byte[] chunk = new byte[1048576]; chunk[0] = 1; allocations.Add(chunk); } }
            catch (OutOfMemoryException) { blocked = true; }
            allocations.Clear(); GC.Collect();
            result["memory_blocked"] = blocked; Require(blocked, "memory_limit_not_observed");
        }
        else if (scenario == "child")
        {
            var startup = new Startup(); startup.Size = (uint)Marshal.SizeOf(typeof(Startup)); ProcessInfo child;
            bool created = CreateProcess(Self, new StringBuilder(Quote(Self) + " --synthetic-leaf " + Quote(Path.Combine(directory, "leaf.txt"))), IntPtr.Zero, IntPtr.Zero, false, 0x08000000, IntPtr.Zero, directory, ref startup, out child);
            int error = Marshal.GetLastWin32Error();
            if (created) { TerminateProcess(child.Process, 125); WaitForSingleObject(child.Process, 5000); CloseHandle(child.Thread); CloseHandle(child.Process); }
            Require(!created && !File.Exists(Path.Combine(directory, "leaf.txt")), "child_limit_not_observed");
            result["child_blocked"] = true; result["child_error"] = error;
        }
        else Require(scenario == "success", "synthetic_case");
        return result;
    }
#else
    static object Get(object target, string name)
    { return target.GetType().InvokeMember(name, BindingFlags.GetProperty, null, target, null, CultureInfo.InvariantCulture); }
    static object Call(object target, string name, params object[] args)
    { return target.GetType().InvokeMember(name, BindingFlags.InvokeMethod, null, target, args, CultureInfo.InvariantCulture); }
    static Dictionary<string, object> NativeProbe(Dictionary<string, object> approval)
    {
        using (var user = RegistryKey.OpenBaseKey(RegistryHive.CurrentUser, RegistryView.Registry64))
        using (var machine = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
        using (var clsidKey = machine.OpenSubKey(@"SOFTWARE\Classes\V83.COMConnector\CLSID"))
        {
            Require(user.OpenSubKey(@"SOFTWARE\Classes\V83.COMConnector") == null && clsidKey != null, "com_registration");
            string clsid = clsidKey.GetValue("") as string; Guid parsed;
            Require(Guid.TryParseExact(clsid, "B", out parsed), "com_clsid");
            Require(user.OpenSubKey(@"SOFTWARE\Classes\CLSID\" + clsid) == null, "user_com_override");
            using (var server = machine.OpenSubKey(@"SOFTWARE\Classes\CLSID\" + clsid + @"\InprocServer32"))
                Require(server != null && String.Equals(server.GetValue("") as string, Dll, StringComparison.OrdinalIgnoreCase), "com_inproc_path");
        }
        NoReparse(Dll); Require(FileVersionInfo.GetVersionInfo(Dll).FileVersion == "8.3.18.1661" && FileHash(Dll) == Text(approval, "com_dll_sha256"), "com_version_hash");
        object connector = null, connection = null, module = null;
        try
        {
            NativeActivationAttempted = true;
            connector = Activator.CreateInstance(Type.GetTypeFromProgID("V83.COMConnector", true));
            connection = Call(connector, "Connect", "File=\"D:\\CRM-ESCHF-001-Isolated\\ka_eschf_test\";");
            module = Get(connection, Module); object handshake = Call(module, "ПроверитьИзолированныйКонтекст");
            Require((string)Get(handshake, "marker") == Marker && (string)Get(handshake, "configuration_name") == Configuration &&
                (string)Get(handshake, "configuration_version") == "2.4.14.182" && (string)Get(handshake, "scope") == "isolated_context_probe_only", "runtime_handshake");
            object probe = Call(module, "ПроверитьИзолированныеСообщения");
            var result = Map("scope", "synthetic_message_probe_only", "native_com_invoked", true, "AC03", false, "native_final_bytes", null, "marker", Marker);
            foreach (string key in new[] {"messages_before", "messages_after"})
            {
                object messages = Get(probe, key); int count = Convert.ToInt32(Call(messages, "Count"), CultureInfo.InvariantCulture);
                Require(count >= 0 && count <= 64, "message_count"); var texts = new List<string>();
                for (int i = 0; i < count; i++) { string text = Call(messages, "Get", i) as string; Require(text != null && text.Length <= 4096, "message_size"); texts.Add(text); }
                result[key] = texts;
            }
            var after = (List<string>)result["messages_after"];
            Require(after.Count == 1 && after[0] == "CRM-ESCHF-001 synthetic queue sentinel", "message_sentinel"); return result;
        }
        finally
        {
            foreach (object value in new[] {module, connection, connector})
                if (value != null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value);
        }
    }
#endif

    [STAThread] static int Main(string[] args)
    {
        try
        {
            if (args.Length == 4 && args[0] == "--worker" && args[2] == "--request-sha256") return Worker(args[1], args[3]);
#if SYNTHETIC_BACKEND
            if (args.Length == 2 && args[0] == "--synthetic-leaf") { File.WriteAllText(args[1], "synthetic-only"); return 0; }
            Require(args.Length == 4 && args[0] == "--synthetic-case" && args[2] == "--evidence-parent", "synthetic_args");
            Require(Array.IndexOf(new[] {"success", "hang", "output", "memory", "child"}, args[1]) >= 0, "synthetic_case");
            return Supervise(Path.GetFullPath(args[3]), null, null, args[1]);
#else
            Require(args.Length == 4 && args[0] == "--approved-p2" && args[2] == "--approved-p2-sha256", "exact_p2_arguments_required");
            Approval(args[1], args[3]); StandPath(Root + @"\evidence");
            return Supervise(Root + @"\evidence", args[1], args[3], null);
#endif
        }
        catch (Exception failure)
        {
            try { Console.Error.WriteLine(Json.Serialize(Map("failure", failure is InvalidOperationException ? failure.Message : failure.GetType().Name,
                "native_activation_attempted", NativeActivationAttempted, "AC03", false))); } catch { }
            return 64;
        }
    }
}
